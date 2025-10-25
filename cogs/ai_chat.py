# cogs/ai_chat.py
import os
import discord
from discord.ext import commands
from discord import app_commands

# Try to import google.generativeai if available. If not, we will show helpful errors.
try:
    import google.generativeai as genai  # type: ignore
    _HAS_GENAI = True
except Exception:
    genai = None  # type: ignore
    _HAS_GENAI = False

# Environment variable names the cog reads:
# - GEMINI_API or GEMINI_API_KEY  -> the API key (required to use Gemini)
# - GEMINI_MODEL                 -> optional model name (default: "chat-bison-001")
# - ADMINS                       -> optional comma separated admin IDs allowed to use /ask (besides guild admins)
GEMINI_API = os.getenv("GEMINI_API") or os.getenv("GEMINI_API_KEY") or ""
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "chat-bison-001")
ADMINS_RAW = os.getenv("ADMINS", "")


def _parse_admins() -> list[int]:
    if not ADMINS_RAW:
        return []
    try:
        return [int(x.strip()) for x in ADMINS_RAW.split(",") if x.strip()]
    except Exception:
        return []


ADMINS = _parse_admins()


class AIChatCog(commands.Cog, name="AI Chat (Gemini)"):
    """Simple Gemini-only AI cog. Uses google.generativeai if available and GEMINI_API key from env."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.model = GEMINI_MODEL
        self.api_key = GEMINI_API.strip()
        self.available = False

        if not self.api_key:
            print("[ai_chat] GEMINI_API not set in environment. Gemini commands will be disabled.")
            self.available = False
            return

        if not _HAS_GENAI:
            print("[ai_chat] google.generativeai library not installed. Install `google-generativeai` to enable Gemini.")
            self.available = False
            return

        # configure the genai client
        try:
            genai.configure(api_key=self.api_key)
            # one-time test call is avoided to be non-blocking at startup; rely on runtime errors instead
            self.available = True
            print(f"[ai_chat] Gemini configured (model={self.model}).")
        except Exception as e:
            self.available = False
            print(f"[ai_chat] Failed to configure google.generativeai: {e}")

    # ---------- helper ----------
    def _is_allowed(self, user: discord.User | discord.Member) -> bool:
        # server administrators are allowed
        try:
            if isinstance(user, discord.Member) and user.guild_permissions.administrator:
                return True
        except Exception:
            pass
        # explicit admin IDs from ADMINS env
        if user.id in ADMINS:
            return True
        return False

    # ---------- slash command ----------
    @app_commands.command(name="ask", description="Ask the Gemini AI a question (admins/ADMINS only).")
    @app_commands.describe(prompt="What you want to ask the AI")
    async def ask(self, interaction: discord.Interaction, prompt: str):
        # Availability checks
        if not self.available:
            # Helpful diagnostic to the admin who tries
            if not self.api_key:
                return await interaction.response.send_message(
                    "❌ GEMINI_API key is not configured (environment variable GEMINI_API or GEMINI_API_KEY).", ephemeral=True
                )
            if not _HAS_GENAI:
                return await interaction.response.send_message(
                    "❌ The python package `google-generativeai` is not installed on this runtime. "
                    "Install it (pip install google-generativeai) or use a runtime that has it.", ephemeral=True
                )
            return await interaction.response.send_message("❌ Gemini is not available (configuration error).", ephemeral=True)

        # Permission check
        member = interaction.user
        if interaction.guild:  # invoked in a guild
            # allow guild administrators or IDs in ADMINS env
            if not self._is_allowed(member):
                return await interaction.response.send_message("❌ You are not allowed to use this command.", ephemeral=True)
        else:
            # DMs: allow only explicit ADMINS
            if member.id not in ADMINS:
                return await interaction.response.send_message("❌ This command is restricted in DMs.", ephemeral=True)

        # Defer while we call the API
        await interaction.response.defer(thinking=True, ephemeral=False)

        try:
            # Use the chat completion style (most compatible)
            # messages format: [{"author":"user","content":"..."}]
            resp = genai.chat.completions.create(
                model=self.model,
                messages=[{"author": "user", "content": prompt}],
                temperature=0.6,
                max_output_tokens=800,
            )
            # response candidates: resp.candidates[0].content
            answer = None
            try:
                # new clients often expose candidates
                if getattr(resp, "candidates", None):
                    answer = resp.candidates[0].content
                elif getattr(resp, "output", None):
                    # some variants
                    output = resp.output
                    # try to extract text
                    if isinstance(output, list) and len(output) > 0 and getattr(output[0], "content", None):
                        answer = output[0].content[0].text
                # fallback: string-convert
                if answer is None:
                    answer = str(resp)
            except Exception:
                answer = str(resp)

            # limit length for embed but attach full if needed
            max_embed_chars = 3900
            if len(answer) > max_embed_chars:
                short = answer[:max_embed_chars] + "…"
            else:
                short = answer

            embed = discord.Embed(title="🤖 Gemini", description=short, color=discord.Color.blue())
            embed.set_footer(text=f"Model: {self.model} • Requested by {interaction.user.display_name}")
            embed.add_field(name="Your prompt", value=f"```{(prompt[:1000] + '...') if len(prompt) > 1000 else prompt}```", inline=False)

            await interaction.followup.send(embed=embed)

            # If answer was long, also send it as a file so nothing gets lost (optional)
            if len(answer) > max_embed_chars:
                # send full text as a .txt file
                file_bytes = answer.encode("utf-8")
                fname = "gemini_full_response.txt"
                discord_file = discord.File(fp=io.BytesIO(file_bytes), filename=fname)
                await interaction.followup.send(content="Full response attached:", file=discord_file)

        except Exception as e:
            # return helpful diagnostic to the user (don't leak sensitive info)
            await interaction.followup.send(f"❌ Gemini API error: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AIChatCog(bot))
