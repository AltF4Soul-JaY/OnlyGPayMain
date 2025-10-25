# main.py (use python main.py to start bot)
import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Import the web server and the web worker modules
import web
import cogs.web_worker

# =================================================================================
# DEFINE THE BOT'S CLASS
# =================================================================================
class OnlyGPayBot(commands.Bot):
    def __init__(self):
        # Define intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True 
        intents.reactions = True
        intents.guilds = True 

        # Initialize bot
        super().__init__(command_prefix='gpay ', intents=intents)

    async def load_cogs(self):
        """Dynamically load all cogs, ensuring core cogs are loaded first."""
        print("Loading cogs...")

        # Cogs to load first (e.g., core services)
        core_cogs_to_load_first = [
            "jamming_core",
            "jamming_user",
            "jamming_admin_commands",
        ]

        # Manually add web_worker.py to the loaded list
        # This prevents the loop below from loading it as a cog
        loaded_filenames = ['web_worker.py']

        # Load core cogs first
        for cog_name in core_cogs_to_load_first:
            try:
                await self.load_extension(f'cogs.{cog_name}')
                print(f'-> Loaded Core Cog: {cog_name}.py')
                loaded_filenames.append(f'{cog_name}.py')
            except Exception as e:
                print(f'[ERROR] Failed to load core cog {cog_name.py}: {e}')

        # Load all other cogs dynamically
        for filename in os.listdir('./cogs'):
            # Load file if it's a .py file, not a helper, and not already loaded
            if filename.endswith('.py') and not filename.startswith('_') and filename not in loaded_filenames:
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f'-> Loaded Cog: {filename}')
                except Exception as e:
                    print(f'[ERROR] Failed to load cog {filename}: {e}')

    async def setup_hook(self):
        """Runs after login but before full connection."""
        print("Running setup hook...")
        await self.load_cogs()
        try:
            # Sync global commands
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} slash command(s).")
        except Exception as e:
            print(f"Failed to sync slash commands: {e}")

    async def on_ready(self):
        """Called when the bot is ready and online."""
        print("-" * 30)
        print(f'{self.user.name} has connected to Discord!')
        print(f'User ID: {self.user.id}')
        print("-" * 30)

# =================================================================================
# MAIN ASYNC FUNCTION TO RUN THE BOT
# =================================================================================
async def main():
    load_dotenv()
    print("Loading environment variables...")

    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

    if not DISCORD_TOKEN:
        print("CRITICAL: DISCORD_TOKEN not found in .env file. Bot cannot start.")
        return

    # Get the main asyncio event loop
    loop = asyncio.get_event_loop()

    # Create the bot instance
    bot = OnlyGPayBot() 

    # --- Setup Web Components ---
    # Pass the bot instance to the web_worker so it can send messages
    cogs.web_worker.setup(bot)
    print("Web worker has received the bot instance.")

    # Pass the event loop and the worker module to the web server
    web.setup(loop, cogs.web_worker)
    print("Web server has received the event loop and web worker.")

    # Start the Flask web server in a separate thread
    try:
        web.start_thread() 
        print("✅ Flask web server started successfully.")
    except Exception as e:
        print(f"⚠️ Failed to start web server: {e}")
        return # Can't continue if the web server fails

    # Start the bot
    await bot.start(DISCORD_TOKEN)

# =================================================================================
# SCRIPT ENTRY POINT
# =================================================================================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")