import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
from typing import Optional, Dict
import datetime
import io
import re
import json
import html

# --- Environment & Configuration ---
if not os.path.exists('./data'):
    os.makedirs('./data')

ADMIN_IDS = {int(admin_id) for admin_id in os.getenv("ADMINS", "").split(',') if admin_id}
CONFIG_FILE_PATH = "./data/config.json"

GUILD_CONFIG = {}

def save_config():
    with open(CONFIG_FILE_PATH, 'w') as f: json.dump(GUILD_CONFIG, f, indent=4)

def load_config():
    global GUILD_CONFIG
    try:
        with open(CONFIG_FILE_PATH, 'r') as f:
            GUILD_CONFIG = {int(k): v for k, v in json.load(f).items()}
            print("Successfully loaded persistent booking configuration.")
    except (FileNotFoundError, json.JSONDecodeError):
        GUILD_CONFIG = {}

# --- Helper Functions ---
def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id not in ADMIN_IDS:
            await interaction.response.send_message("❌ **Access Denied**", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

async def generate_transcript(channel: discord.TextChannel) -> io.BytesIO:
    html_content = f"""<html><head><title>Transcript for {channel.name}</title><style>body{{font-family:sans-serif;background-color:#36393f;color:#dcddde;}} .message{{display:flex;margin-bottom:1em;}} .avatar img{{width:40px;height:40px;border-radius:50%;margin-right:10px;}} .username{{font-weight:bold;}} .timestamp{{color:#72767d;font-size:.8em;}}</style></head><body><h1>Transcript for #{channel.name}</h1>"""
    async for msg in channel.history(limit=None, oldest_first=True):
        # FIX: Use the standard html library to escape content.
        escaped_content = html.escape(msg.clean_content)
        html_content += f"""<div class="message"><div class="avatar"><img src="{msg.author.display_avatar.url}"></div><div><span class="username">{msg.author.display_name}</span><span class="timestamp">{msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")}</span><div>{escaped_content}</div></div></div>"""
    html_content += "</body></html>"
    return io.BytesIO(html_content.encode('utf-8'))

# --- Main Cog Class ---
class ArtistBooking(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        load_config()
        self.bot.add_view(self.CreateBookingView(self))
        self.bot.add_view(self.BookingControlView(self))
        self.bot.add_view(self.ClosedTicketView(self)) # Add the new view

    # --- UI Components as Inner Classes ---
    class BookingFormModal(discord.ui.Modal, title="🎤 Artist Booking Form"):
        # This modal is stable and does not need changes.
        def __init__(self, cog_instance): super().__init__(); self.cog = cog_instance
        event_name = discord.ui.TextInput(label="Event Name", placeholder="e.g., Starlight Music Festival")
        event_date = discord.ui.TextInput(label="Proposed Date & Time", placeholder="e.g., 25 Dec 2025 at 9:00 PM IST")
        venue = discord.ui.TextInput(label="Venue / Location", placeholder="e.g., Discord Server / Mumbai, India")
        budget = discord.ui.TextInput(label="Proposed Budget (INR)", placeholder="e.g., 75000")
        description = discord.ui.TextInput(label="Event Details", style=discord.TextStyle.paragraph, required=False)

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            config = GUILD_CONFIG.get(interaction.guild.id)
            if not config: return await interaction.followup.send("❌ **Error:** Booking system misconfigured.", ephemeral=True)
            category = interaction.guild.get_channel(config['category_id'])
            if not category: return await interaction.followup.send("❌ **Error:** Configured category not found.", ephemeral=True)
            overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
            for admin_id in ADMIN_IDS:
                if admin := interaction.guild.get_member(admin_id): overwrites[admin] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            ticket_channel = await category.create_text_channel(f"booking-{interaction.user.display_name}", overwrites=overwrites)
            ticket_data = {"requester_id": interaction.user.id, "status": "pending", "event_name": self.event_name.value, "event_date": self.event_date.value, "venue": self.venue.value, "budget": self.budget.value, "description": self.description.value}
            with open(f"./data/{ticket_channel.id}.json", 'w') as f: json.dump(ticket_data, f, indent=4)
            embed = discord.Embed(title=f"🎶 Booking Request: {self.event_name.value}", color=discord.Color.gold())
            embed.add_field(name="👤 Requester", value=interaction.user.mention, inline=False).add_field(name="🗓️ Date & Time", value=self.event_date.value).add_field(name="📍 Venue", value=self.venue.value).add_field(name="💰 Budget (INR)", value=self.budget.value)
            if self.description.value: embed.add_field(name="📝 Details", value=self.description.value, inline=False)
            await ticket_channel.send(embed=embed, view=self.cog.BookingControlView(self.cog))
            await interaction.followup.send(f"✅ **Success!** Your ticket is at {ticket_channel.mention}", ephemeral=True)

    class CreateBookingView(discord.ui.View):
        def __init__(self, cog_instance):
            super().__init__(timeout=None)
            self.cog = cog_instance
        # FIX: Added custom emoji
        @discord.ui.button(label="Book The Artist", style=discord.ButtonStyle.primary, custom_id="create_booking_persistent_final", emoji="<a:ticket_shiny:1423897615228997683>")
        async def create_booking(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.guild.id not in GUILD_CONFIG:
                return await interaction.response.send_message("❌ **Error:** Booking system not configured.", ephemeral=True)
            await interaction.response.send_modal(self.cog.BookingFormModal(self.cog))

    class ApprovalFormModal(discord.ui.Modal, title="Confirm & Approve Booking"):
        def __init__(self, current_data: dict, original_message: discord.Message):
            super().__init__(); self.current_data = current_data; self.original_message = original_message
            self.event_name = discord.ui.TextInput(label="Event Name", default=current_data.get('event_name'))
            self.event_date = discord.ui.TextInput(label="Date & Time", default=current_data.get('event_date'))
            self.venue = discord.ui.TextInput(label="Venue / Location", default=current_data.get('venue'))
            self.budget = discord.ui.TextInput(label="Final Budget (INR)", default=current_data.get('budget'))
            self.add_item(self.event_name); self.add_item(self.event_date); self.add_item(self.venue); self.add_item(self.budget)

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            self.current_data.update({'event_name': self.event_name.value, 'event_date': self.event_date.value, 'venue': self.venue.value, 'budget': self.budget.value, 'status': 'approved'})
            with open(f"./data/{interaction.channel.id}.json", 'w') as f: json.dump(self.current_data, f, indent=4)
            
            view = self.original_message.view; [setattr(item, 'disabled', True) for item in view.children]; await self.original_message.edit(view=view)
            
            requester = interaction.guild.get_member(self.current_data['requester_id'])
            if requester: await interaction.channel.set_permissions(requester, send_messages=False)
            
            embed = discord.Embed(title="🎉 Booking Confirmed!", color=discord.Color.green())
            embed.add_field(name="Event", value=self.event_name.value).add_field(name="Date", value=self.event_date.value).add_field(name="Venue", value=self.venue.value)
            
            user_mention = requester.mention if requester else f"<@{self.current_data['requester_id']}>"
            await interaction.channel.send(content=f"Congratulations {user_mention}, your booking is confirmed!", embed=embed)
            await interaction.followup.send("✅ Booking approved.", ephemeral=True)

    class DenialReasonModal(discord.ui.Modal, title="Deny Booking"):
        # This modal is stable and does not need changes.
        def __init__(self, current_data: dict, original_message: discord.Message):
            super().__init__(); self.current_data = current_data; self.original_message = original_message
            self.reason = discord.ui.TextInput(label="Reason for Denial (Optional)", style=discord.TextStyle.paragraph, required=False)
            self.add_item(self.reason)
        
        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            self.current_data.update({'status': 'denied'})
            with open(f"./data/{interaction.channel.id}.json", 'w') as f: json.dump(self.current_data, f, indent=4)
            view = self.original_message.view; [setattr(item, 'disabled', True) for item in view.children]; await self.original_message.edit(view=view)
            requester = interaction.guild.get_member(self.current_data['requester_id'])
            if requester: await interaction.channel.set_permissions(requester, send_messages=False)
            embed = discord.Embed(title="Booking Request Update", description=f"The request for **{self.current_data['event_name']}** has been denied.", color=discord.Color.red())
            if self.reason.value: embed.add_field(name="Reason", value=self.reason.value)
            user_mention = requester.mention if requester else f"<@{self.current_data['requester_id']}>"
            await interaction.channel.send(content=user_mention, embed=embed)
            await interaction.followup.send("Booking denied.", ephemeral=True)

    # --- TICKET CONTROL VIEWS ---
    class BookingControlView(discord.ui.View):
        def __init__(self, cog_instance):
            super().__init__(timeout=None)
            self.cog = cog_instance
        
        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id not in ADMIN_IDS:
                await interaction.response.send_message("❌ **Access Denied** | You are not an authorized booking manager.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="booking_approve_final", emoji="✅")
        async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
            try:
                with open(f"./data/{interaction.channel.id}.json", 'r') as f: current_data = json.load(f)
                if current_data['status'] != 'pending': return await interaction.response.send_message("This ticket has already been actioned.", ephemeral=True)
                await interaction.response.send_modal(self.cog.ApprovalFormModal(current_data, interaction.message))
            except FileNotFoundError: await interaction.response.send_message("❌ Error: Could not find data for this ticket.", ephemeral=True)

            embed = discord.Embed(description=f"Ticket Approved by {interaction.user.mention}", color=discord.Color.dark_blue())
            await interaction.channel.send(embed=embed, view=self.cog.ApproveTicketView(self.cog))     


        @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="booking_deny_final", emoji="✖️")
        async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
            try:
                with open(f"./data/{interaction.channel.id}.json", 'r') as f: current_data = json.load(f)
                if current_data['status'] != 'pending': return await interaction.response.send_message("This ticket has already been actioned.", ephemeral=True)
                await interaction.response.send_modal(self.cog.DenialReasonModal(current_data, interaction.message))
            except FileNotFoundError: await interaction.response.send_message("❌ Error: Could not find data for this ticket.", ephemeral=True)
        
        @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="booking_close_final", emoji="🔒")
        async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.defer()
            [setattr(item, 'disabled', True) for item in self.children]; await interaction.message.edit(view=self)
            
            try:
                with open(f"./data/{interaction.channel.id}.json", 'r+') as f:
                    data = json.load(f)
                    data['status'] = 'closed'
                    f.seek(0); json.dump(data, f, indent=4); f.truncate()
                    requester = interaction.guild.get_member(data['requester_id'])
                    if requester:
                        await interaction.channel.set_permissions(requester, view_channel=False)
            except FileNotFoundError:
                await interaction.followup.send("Could not find ticket data file.", ephemeral=True)
                return

            embed = discord.Embed(description=f"Ticket closed by {interaction.user.mention}", color=discord.Color.dark_orange())
            await interaction.channel.send(embed=embed, view=self.cog.ClosedTicketView(self.cog))

    class ClosedTicketView(discord.ui.View):
        def __init__(self, cog_instance):
            super().__init__(timeout=None)
            self.cog = cog_instance
        
        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id not in ADMIN_IDS:
                await interaction.response.send_message("❌ **Access Denied** | You are not an authorized booking manager.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Re-Open", style=discord.ButtonStyle.success, custom_id="booking_reopen_final", emoji="🔓")
        async def reopen(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.defer()
            try:
                with open(f"./data/{interaction.channel.id}.json", 'r+') as f:
                    data = json.load(f)
                    data['status'] = 'pending'
                    f.seek(0); json.dump(data, f, indent=4); f.truncate()
                    requester = interaction.guild.get_member(data['requester_id'])
                    if requester:
                        await interaction.channel.set_permissions(requester, view_channel=True)
            except FileNotFoundError: return
            
            await interaction.message.delete()
            await interaction.channel.send(f"🔓 Ticket re-opened by {interaction.user.mention}")

        @discord.ui.button(label="Transcript", style=discord.ButtonStyle.secondary, custom_id="booking_transcript_final", emoji="📄")
        async def transcript(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.defer(ephemeral=True)
            transcript_file = await generate_transcript(interaction.channel)
            await interaction.followup.send("Here is the transcript for this ticket:", file=discord.File(transcript_file, f"transcript-{interaction.channel.name}.html"))

        @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="booking_delete_final", emoji="⛔")
        async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_message("⛔ Deleting this ticket permanently...")
            ticket_file_path = f"./data/{interaction.channel.id}.json"
            await asyncio.sleep(3)
            await interaction.channel.delete()
            if os.path.exists(ticket_file_path): os.remove(ticket_file_path)

    booking_group = app_commands.Group(name="booking", description="Commands for the artist booking system.")

    @booking_group.command(name="setup", description="[Admin] Deploys and saves the artist booking panel.")
    @is_admin()
    @app_commands.describe(channel="Channel for the 'Create Booking' button.", category="Category for new booking channels.", transcript_channel="Channel for transcripts.")
    async def setup(self, interaction: discord.Interaction, channel: discord.TextChannel, category: discord.CategoryChannel, transcript_channel: discord.TextChannel, title: str = None, description: str = None):
        await interaction.response.defer(ephemeral=True)
        GUILD_CONFIG[interaction.guild.id] = {'channel_id': channel.id, 'category_id': category.id, 'transcript_channel_id': transcript_channel.id}
        save_config()
        embed = discord.Embed(title=title or "🎤 Artist Booking", description=description or "Ready to make your event unforgettable? Click the button below!", color=discord.Color.dark_magenta())
        await channel.send(embed=embed, view=self.CreateBookingView(self))
        await interaction.followup.send(f"✅ **Panel Deployed & Saved!**", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ArtistBooking(bot))
