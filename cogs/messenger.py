import discord
from discord.ext import commands
from os import getenv

OWNER_ID = 741140140201607268  # your Discord ID


class ActCog(commands.Cog):
    def __init__(self, bot, admins):
        self.bot = bot
        self.ADMINS = admins
        self.message_map = {}  # DM msg_id ↔ (channel_id, user_id)

    # --------------------------
    # COMMAND
    # --------------------------
    @commands.command()
    async def send_message(self, ctx, channel_id: int, *, text: str):
        """Send a message to a server channel via DM (admin only)."""
        if ctx.author.id not in self.ADMINS:
            await ctx.send("❌ You are not authorized to use this command.")
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            await ctx.send("❌ Invalid channel ID.")
            return

        sent_msg = await channel.send(text)
        await ctx.send(f"✅ Message sent to {channel.mention}!")
        # keep track of the sent message
        self.message_map[sent_msg.id] = (channel.id, None)

    # --------------------------
    # EVENT LISTENER
    # --------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return  # ignore self

        # Handle admin DM reply → send to channel
        if isinstance(message.channel, discord.DMChannel):
            if message.author.id in self.ADMINS and message.reference:
                ref_msg = message.reference.resolved
                if ref_msg:
                    mapped = self.message_map.get(ref_msg.id)
                    if mapped:
                        channel_id, user_id = mapped
                        channel = self.bot.get_channel(channel_id)
                        if channel:
                            if user_id:
                                user_mention = f"<@{user_id}>"
                                await channel.send(f"{user_mention} {message.content}")
                            else:
                                await channel.send(message.content)
            return

        # Handle mentions or replies to bot → send DM to owner
        if self.bot.user in message.mentions or (
            message.reference and getattr(message.reference.resolved, "author", None) == self.bot.user
        ):
            owner = await self.bot.fetch_user(OWNER_ID)

            embed = discord.Embed(
                description=message.content or "[No text]",
                color=discord.Color.blurple()
            )
            embed.set_author(
                name=f"{message.author} | {message.channel.name}",
                icon_url=message.author.display_avatar.url
            )
            embed.set_footer(text=f"Channel ID: {message.channel.id}")

            dm_msg = await owner.send(embed=embed)
            # Map the DM message ID → (channel_id, user_id)
            self.message_map[dm_msg.id] = (message.channel.id, message.author.id)


# --------------------------
# SETUP FUNCTION FOR COG
# --------------------------
async def setup(bot):
    ADMINS = list(map(int, getenv("ADMINS", "").split(",")))
    await bot.add_cog(ActCog(bot, ADMINS))
