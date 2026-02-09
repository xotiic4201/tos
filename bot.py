from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
import os
import logging
from datetime import datetime, timedelta
import asyncio
import aiohttp
from dotenv import load_dotenv
import json
import traceback
from typing import Optional, List


# Get the absolute path to the .env file
env_path = Path(__file__).parent / '.env'
print(f"Looking for .env at: {env_path}")

# Load environment variables from .env file
if env_path.exists():
    print(".env file found! Loading...")
    load_dotenv(dotenv_path=env_path)
else:
    print("WARNING: .env file not found!")


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Environment variables
DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', '')
API_URL = os.environ.get('API_URL', 'https://bot-hosting-b.onrender.com')

if not DISCORD_BOT_TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN not found in environment variables")

# Bot class
class VerificationBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None
        )
        
        self.api_url = API_URL
        self.synced_commands = False
    
    async def setup_hook(self):
        # Add a delay before syncing
        await asyncio.sleep(2)
        
        # Sync commands globally
        try:
            await self.tree.sync()
            logger.info("Commands synced successfully")
            self.synced_commands = True
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
    
    async def on_ready(self):
        logger.info(f"Bot is ready! Logged in as {self.user.name} ({self.user.id})")
        
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for /verify commands"
            )
        )
        
        # Try to sync commands again if needed
        if not self.synced_commands:
            try:
                await self.tree.sync()
                logger.info("Commands synced on ready")
                self.synced_commands = True
            except Exception as e:
                logger.error(f"Failed to sync commands on ready: {e}")

# Verification cog with enhanced commands
class VerificationCog(commands.Cog):
    def __init__(self, bot: VerificationBot):
        self.bot = bot
        self.session = aiohttp.ClientSession()
    
    async def cog_unload(self):
        await self.session.close()
    
    # Error handler for app commands
    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        logger.error(f"Command error: {error}", exc_info=True)
        
        if isinstance(error, app_commands.CommandInvokeError):
            original = error.original
            if isinstance(original, discord.errors.NotFound) and "Unknown interaction" in str(original):
                # Try to send a followup message instead
                try:
                    await interaction.followup.send(
                        "⚠️ Interaction timed out. Please try the command again.",
                        ephemeral=True
                    )
                except:
                    pass
                return
        
        # For other errors, try to respond
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"❌ An error occurred: {str(error)}",
                    ephemeral=True
                )
        except:
            pass
    
    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """When bot joins a new server"""
        logger.info(f"Joined guild: {guild.name} ({guild.id})")
        
        # Try to find a channel to send welcome message
        try:
            # First try system channel
            if guild.system_channel:
                channel = guild.system_channel
            # Then try first text channel
            else:
                channel = guild.text_channels[0] if guild.text_channels else None
            
            if channel:
                embed = discord.Embed(
                    title="✅ xotiicsverify Bot Added",
                    description="Thanks for adding me to your server!",
                    color=discord.Color.green()
                )
                
                embed.add_field(
                    name="Getting Started",
                    value="Use `/send` to create a verification embed\n"
                          "Use `/dashboard` to access the web dashboard\n"
                          "Use `/help` for more commands",
                    inline=False
                )
                
                embed.set_footer(text="Type /help for all commands")
                await channel.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Failed to send welcome message to {guild.name}: {e}")
    
    @app_commands.command(name="help", description="Show all available commands")
    async def help_command(self, interaction: discord.Interaction):
        """Show help information"""
        embed = discord.Embed(
            title="🤖 xotiicsverify Bot Help",
            description="All available commands for the verification system",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="📋 Verification",
            value="• `/send` - Create verification embed\n"
                  "• `/verify` - Manual verification (admins only)\n"
                  "• `/stats` - View verification statistics",
            inline=False
        )
        
        embed.add_field(
            name="🔄 Transfer & Restoration",
            value="• `/transfer` - Transfer users between servers\n"
                  "• `/restore` - Restore verified users\n"
                  "• `/cleanup` - Clean up old/unverified users",
            inline=False
        )
        
        embed.add_field(
            name="⚙️ Configuration",
            value="• `/config` - Configure bot settings\n"
                  "• `/dashboard` - Get dashboard link\n"
                  "• `/logs` - View recent verification logs",
            inline=False
        )
        
        embed.set_footer(text="xotiicsverify | Secure Verification System")
        embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
    
    # Send verification embed command - FIXED
    @app_commands.command(name="send", description="Send verification embed to a channel")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(channel="Channel to send the embed to (default: current channel)")
    async def send_verification(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        """Send a verification embed with button"""
        try:
            # Defer the response immediately to avoid timeout
            await interaction.response.defer(ephemeral=True, thinking=True)
            
            target_channel = channel or interaction.channel
            
            if not target_channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.followup.send(
                    "❌ I don't have permission to send messages in that channel.",
                    ephemeral=True
                )
                return
            
            # Get verification URL from API
            try:
                async with self.session.get(f"{self.bot.api_url}/api/verify/{interaction.guild.id}") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        verification_url = data.get('verification_url')
                    else:
                        verification_url = f"{self.bot.api_url}/oauth/callback?guild_id={interaction.guild.id}"
            except Exception as e:
                logger.error(f"Failed to get verification URL: {e}")
                verification_url = f"{self.bot.api_url}/verify/{interaction.guild.id}"
            
            # Create embed
            embed = discord.Embed(
                title="🔐 Server Verification Required",
                description="Click the button below to verify your account and gain access to this server.",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            
            embed.add_field(
                name="📋 Instructions",
                value="1. Click the **Verify Now** button\n"
                      "2. Login with Discord\n"
                      "3. Authorize the permissions\n"
                      "4. You'll be automatically verified!",
                inline=False
            )
            
            embed.add_field(
                name="🔒 Security",
                value="Your data is encrypted and secure. We only request necessary permissions.",
                inline=False
            )
            
            embed.set_footer(text="xotiicsverify | Secure Verification System")
            embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            
            # Create view with button
            view = discord.ui.View(timeout=None)
            view.add_item(
                discord.ui.Button(
                    style=discord.ButtonStyle.link,
                    label="Verify Now",
                    emoji="✅",
                    url=verification_url
                )
            )
            
            # Send embed to target channel
            await target_channel.send(embed=embed, view=view)
            
            await interaction.followup.send(
                f"✅ Verification embed sent to {target_channel.mention}!",
                ephemeral=True
            )
            
        except Exception as e:
            logger.error(f"Error sending verification embed: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ Failed to send verification embed. Please try again.",
                    ephemeral=True
                )
            except:
                pass
    
    # TRANSFER COMMAND - NEW
    @app_commands.command(name="transfer", description="Transfer verified users from another server")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        source_server_id="ID of the server to transfer users FROM",
        limit="Maximum number of users to transfer (0 for all)",
        assign_role="Role to assign to transferred users",
        delete_from_source="Remove users from source server after transfer"
    )
    async def transfer_users(
        self,
        interaction: discord.Interaction,
        source_server_id: str,
        limit: app_commands.Range[int, 0, 1000] = 0,
        assign_role: Optional[discord.Role] = None,
        delete_from_source: bool = False
    ):
        """Transfer verified users from another server to this one"""
        try:
            await interaction.response.defer(ephemeral=False, thinking=True)
            
            # Check if source server is valid
            try:
                source_guild = self.bot.get_guild(int(source_server_id))
                if not source_guild:
                    await interaction.followup.send(
                        "❌ Source server not found or bot is not in that server.",
                        ephemeral=True
                    )
                    return
                
                # Check if bot has permission in source server
                source_me = source_guild.get_member(self.bot.user.id)
                if not source_me or not source_me.guild_permissions.administrator:
                    await interaction.followup.send(
                        "⚠️ Bot needs admin permissions in the source server to transfer users.",
                        ephemeral=True
                    )
                    return
                    
            except ValueError:
                await interaction.followup.send(
                    "❌ Invalid server ID format.",
                    ephemeral=True
                )
                return
            
            # Get verified users from source server via API
            try:
                async with self.session.get(f"{self.bot.api_url}/api/dashboard/server/{source_server_id}/members") as resp:
                    if resp.status != 200:
                        await interaction.followup.send(
                            f"❌ Failed to get users from source server (API error: {resp.status})",
                            ephemeral=True
                        )
                        return
                    
                    data = await resp.json()
                    users = data.get('members', [])
                    
                    if not users:
                        await interaction.followup.send(
                            "❌ No verified users found in the source server.",
                            ephemeral=True
                        )
                        return
                    
            except Exception as e:
                logger.error(f"API error: {e}")
                await interaction.followup.send(
                    "❌ Failed to connect to verification API.",
                    ephemeral=True
                )
                return
            
            # Filter users if needed
            if limit > 0 and limit < len(users):
                users = users[:limit]
            
            # Initial progress embed
            embed = discord.Embed(
                title="🔄 Transferring Users",
                description=f"Transferring **{len(users)}** users from `{source_guild.name}` to `{interaction.guild.name}`...",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            
            embed.add_field(name="Source Server", value=source_guild.name, inline=True)
            embed.add_field(name="Target Server", value=interaction.guild.name, inline=True)
            embed.add_field(name="Users to Transfer", value=str(len(users)), inline=True)
            
            if assign_role:
                embed.add_field(name="Role to Assign", value=assign_role.mention, inline=True)
            
            embed.set_footer(text="This may take a while...")
            
            await interaction.edit_original_response(embed=embed)
            
            transferred = 0
            failed = 0
            already_member = 0
            
            # Process users
            for user_data in users:
                try:
                    user_id = user_data.get('discord_id')
                    username = user_data.get('username', 'Unknown')
                    
                    # Check if user is already in target server
                    try:
                        target_member = await interaction.guild.fetch_member(int(user_id))
                        already_member += 1
                        
                        # Assign role if specified
                        if assign_role:
                            await target_member.add_roles(assign_role, reason=f"Transferred from {source_guild.name}")
                        
                        transferred += 1
                        
                    except discord.NotFound:
                        # User not in target server, try to add them
                        try:
                            # Get user's access token from backend (you need to implement this)
                            # For now, we'll just try to invite them
                            headers = {
                                'Authorization': f'Bot {os.environ.get("DISCORD_BOT_TOKEN")}',
                                'Content-Type': 'application/json'
                            }
                            
                            # Note: This requires OAuth2 token which should be stored in your backend
                            # You'll need to implement proper user lookup in your API
                            logger.warning(f"Need OAuth token for user {user_id} to add to server")
                            failed += 1
                            continue
                            
                        except Exception as e:
                            logger.error(f"Failed to add user {username}: {e}")
                            failed += 1
                            continue
                    
                    # Remove from source server if requested
                    if delete_from_source:
                        try:
                            source_member = await source_guild.fetch_member(int(user_id))
                            await source_member.kick(reason=f"Transferred to {interaction.guild.name}")
                        except:
                            pass  # User might not be in source server anymore
                    
                    # Update progress every 10 users
                    if transferred % 10 == 0:
                        progress_embed = discord.Embed(
                            title="🔄 Transfer in Progress",
                            description=f"**{transferred}/{len(users)}** users processed",
                            color=discord.Color.orange()
                        )
                        await interaction.edit_original_response(embed=progress_embed)
                    
                    # Rate limiting
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"Error processing user {user_id}: {e}")
                    failed += 1
            
            # Final results embed
            final_embed = discord.Embed(
                title="✅ Transfer Complete",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            final_embed.add_field(name="✅ Transferred", value=str(transferred), inline=True)
            final_embed.add_field(name="⚠️ Already Members", value=str(already_member), inline=True)
            final_embed.add_field(name="❌ Failed", value=str(failed), inline=True)
            final_embed.add_field(name="📊 Total Attempted", value=str(len(users)), inline=False)
            
            if assign_role and transferred > 0:
                final_embed.add_field(name="🎯 Role Assigned", value=assign_role.mention, inline=False)
            
            if delete_from_source:
                final_embed.add_field(name="🗑️ Removed from Source", value="Yes", inline=True)
            
            final_embed.set_footer(text="xotiicsverify | Secure Verification System")
            
            await interaction.edit_original_response(embed=final_embed)
            
        except Exception as e:
            logger.error(f"Transfer error: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    f"❌ Transfer failed: {str(e)}",
                    ephemeral=True
                )
            except:
                pass
    
    # Restore members command - UPDATED
    @app_commands.command(name="restore", description="Restore verified members to server")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        role="Role to assign to restored members",
        limit="Maximum number of users to restore (0 for all)"
    )
    async def restore_members(
        self,
        interaction: discord.Interaction,
        role: Optional[discord.Role] = None,
        limit: app_commands.Range[int, 0, 500] = 0
    ):
        """Restore verified members to the server"""
        try:
            await interaction.response.defer(ephemeral=False, thinking=True)
            
            # Get verified users from API
            async with self.session.get(f"{self.bot.api_url}/api/bot/guild/{interaction.guild.id}/verified") as resp:
                if resp.status != 200:
                    await interaction.followup.send(
                        "❌ Failed to get verified users from API.",
                        ephemeral=True
                    )
                    return
                
                data = await resp.json()
                users = data.get('users', [])
            
            if not users:
                await interaction.followup.send(
                    "❌ No verified users found for this server.",
                    ephemeral=True
                )
                return
            
            # Filter non-restored users
            users = [u for u in users if not u.get('restored', False)]
            
            if not users:
                await interaction.followup.send(
                    "✅ All users are already restored!",
                    ephemeral=True
                )
                return
            
            # Apply limit if specified
            if limit > 0 and limit < len(users):
                users = users[:limit]
            
            # Initial progress embed
            embed = discord.Embed(
                title="🔄 Restoring Members",
                description=f"Restoring **{len(users)}** users...",
                color=discord.Color.orange(),
                timestamp=datetime.now()
            )
            
            if role:
                embed.add_field(name="Role to Assign", value=role.mention, inline=False)
            
            embed.set_footer(text="This may take a while...")
            
            await interaction.edit_original_response(embed=embed)
            
            restored_count = 0
            failed_count = 0
            
            for user in users:
                try:
                    user_id = int(user['discord_id'])
                    username = user.get('username', 'Unknown')
                    
                    # Try to get member
                    try:
                        member = await interaction.guild.fetch_member(user_id)
                        
                        # Assign role if specified
                        if role and role not in member.roles:
                            await member.add_roles(role, reason="Verification restoration")
                        
                        restored_count += 1
                        
                    except discord.NotFound:
                        # Member not in server - we can't add them without OAuth token
                        failed_count += 1
                        continue
                    
                    # Mark as restored in API
                    try:
                        payload = {
                            'member_ids': [user['discord_id']],
                            'role_id': str(role.id) if role else None
                        }
                        async with self.session.post(
                            f"{self.bot.api_url}/api/bot/guild/{interaction.guild.id}/restore",
                            json=payload
                        ) as resp:
                            if resp.status != 200:
                                logger.error(f"Failed to mark user as restored in API: {await resp.text()}")
                    except:
                        pass
                    
                    # Rate limiting
                    await asyncio.sleep(0.5)
                    
                    # Update progress every 10 users
                    if restored_count % 10 == 0:
                        progress_embed = discord.Embed(
                            title="🔄 Restoration in Progress",
                            description=f"**{restored_count}/{len(users)}** users processed",
                            color=discord.Color.orange()
                        )
                        await interaction.edit_original_response(embed=progress_embed)
                    
                except Exception as e:
                    logger.error(f"Error restoring user {username}: {e}")
                    failed_count += 1
            
            # Final results
            final_embed = discord.Embed(
                title="✅ Restoration Complete",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            final_embed.add_field(name="✅ Restored", value=str(restored_count), inline=True)
            final_embed.add_field(name="❌ Failed", value=str(failed_count), inline=True)
            final_embed.add_field(name="📊 Total", value=str(len(users)), inline=True)
            
            if role and restored_count > 0:
                final_embed.add_field(name="🎯 Role Assigned", value=role.mention, inline=False)
            
            final_embed.set_footer(text="xotiicsverify | Secure Verification System")
            
            await interaction.edit_original_response(embed=final_embed)
            
        except Exception as e:
            logger.error(f"Restoration error: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    f"❌ An error occurred during restoration: {str(e)}",
                    ephemeral=True
                )
            except:
                pass
    
    # Stats command
    @app_commands.command(name="stats", description="Show verification statistics")
    async def show_stats(self, interaction: discord.Interaction):
        """Show verification statistics"""
        try:
            # Defer response
            await interaction.response.defer(ephemeral=False, thinking=True)
            
            # Get stats from API
            async with self.session.get(f"{self.bot.api_url}/api/dashboard/server/{interaction.guild.id}/stats") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    stats = data.get('stats', {})
                else:
                    stats = {'total_verified': 0, 'restored': 0, 'pending': 0, 'verified_today': 0}
            
            embed = discord.Embed(
                title="📊 Verification Statistics",
                color=discord.Color.purple(),
                timestamp=datetime.now()
            )
            
            embed.add_field(name="✅ Total Verified", value=str(stats.get('total_verified', 0)), inline=True)
            embed.add_field(name="🔄 Restored", value=str(stats.get('restored', 0)), inline=True)
            embed.add_field(name="⏳ Pending", value=str(stats.get('pending', 0)), inline=True)
            
            if stats.get('verified_today', 0) > 0:
                embed.add_field(name="📈 Verified Today", value=str(stats.get('verified_today', 0)), inline=True)
            
            embed.set_footer(text="xotiicsverify | Secure Verification System")
            embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
            
            await interaction.edit_original_response(embed=embed)
            
        except Exception as e:
            logger.error(f"Stats error: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    "❌ Failed to get statistics. Please try again later.",
                    ephemeral=True
                )
            except:
                pass
    
    # Dashboard command
    @app_commands.command(name="dashboard", description="Get dashboard link")
    async def get_dashboard(self, interaction: discord.Interaction):
        """Get link to web dashboard"""
        embed = discord.Embed(
            title="🌐 Web Dashboard",
            description="Manage your server verification settings via our web dashboard.",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        dashboard_url = "https://bothostingf.vercel.app"
        embed.add_field(
            name="🔗 Dashboard Link",
            value=f"[Click here to access dashboard]({dashboard_url})",
            inline=False
        )
        
        embed.add_field(
            name="📋 Features",
            value="• View verification statistics\n"
                  "• Manage verified members\n"
                  "• Configure bot settings\n"
                  "• View activity logs\n"
                  "• Transfer users between servers",
            inline=False
        )
        
        embed.set_footer(text="xotiicsverify | Secure Verification System")
        
        await interaction.response.send_message(embed=embed)
    
    # Config command - FIXED
    @app_commands.command(name="config", description="Configure bot settings")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        verification_channel="Channel to send verification messages",
        verification_role="Role to assign after verification",
        enable_auto_verification="Enable automatic verification",
        log_channel="Channel to send verification logs"
    )
    async def configure_bot(
        self,
        interaction: discord.Interaction,
        verification_channel: Optional[discord.TextChannel] = None,
        verification_role: Optional[discord.Role] = None,
        enable_auto_verification: Optional[bool] = None,
        log_channel: Optional[discord.TextChannel] = None
    ):
        """Configure bot settings for this server"""
        try:
            # Defer response
            await interaction.response.defer(ephemeral=True, thinking=True)
            
            config = {}
            
            if verification_channel:
                config['verification_channel'] = str(verification_channel.id)
            
            if verification_role:
                config['verification_role'] = str(verification_role.id)
            
            if enable_auto_verification is not None:
                config['enable_auto_verification'] = enable_auto_verification
            
            if log_channel:
                config['log_channel'] = str(log_channel.id)
            
            # Save config to API
            async with self.session.post(
                f"{self.bot.api_url}/api/dashboard/server/{interaction.guild.id}/config",
                json=config
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"Failed to save configuration: {error_text}")
            
            embed = discord.Embed(
                title="⚙️ Configuration Updated",
                description="Bot settings have been saved successfully.",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            if verification_channel:
                embed.add_field(name="Verification Channel", value=verification_channel.mention, inline=True)
            
            if verification_role:
                embed.add_field(name="Verification Role", value=verification_role.mention, inline=True)
            
            if enable_auto_verification is not None:
                embed.add_field(name="Auto Verification", value="Enabled" if enable_auto_verification else "Disabled", inline=True)
            
            if log_channel:
                embed.add_field(name="Log Channel", value=log_channel.mention, inline=True)
            
            embed.set_footer(text="xotiicsverify | Secure Verification System")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Config error: {e}", exc_info=True)
            try:
                await interaction.followup.send(
                    f"❌ Failed to save configuration: {str(e)}",
                    ephemeral=True
                )
            except:
                pass
    
    # Logs command - NEW
    @app_commands.command(name="logs", description="Show recent verification logs")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        limit="Number of logs to show (max 50)",
        log_type="Type of logs to show"
    )
    async def show_logs(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, 50] = 10,
        log_type: Optional[str] = None
    ):
        """Show recent verification logs"""
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            
            # Build query params
            params = {'limit': limit}
            if log_type:
                params['log_type'] = log_type
            
            # Get logs from API
            async with self.session.get(
                f"{self.bot.api_url}/api/dashboard/server/{interaction.guild.id}/logs",
                params=params
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logs = data.get('logs', [])
                else:
                    logs = []
            
            if not logs:
                await interaction.followup.send(
                    "No logs found for this server.",
                    ephemeral=True
                )
                return
            
            embed = discord.Embed(
                title="📝 Recent Verification Logs",
                color=discord.Color.dark_grey(),
                timestamp=datetime.now()
            )
            
            for log in logs[:10]:  # Show max 10 logs in embed
                log_time = datetime.fromisoformat(log['created_at'].replace('Z', '+00:00'))
                time_str = log_time.strftime("%Y-%m-%d %H:%M")
                
                log_type_emoji = {
                    'verification': '✅',
                    'restoration': '🔄',
                    'error': '❌',
                    'config': '⚙️'
                }.get(log.get('type', 'info'), '📝')
                
                embed.add_field(
                    name=f"{log_type_emoji} {time_str}",
                    value=f"**{log.get('type', 'info').title()}**: {log.get('message', 'N/A')}",
                    inline=False
                )
            
            embed.set_footer(text=f"Showing {len(logs[:10])} of {len(logs)} logs")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Logs error: {e}")
            await interaction.followup.send(
                "❌ Failed to get logs. Please try again later.",
                ephemeral=True
            )
    
    # Verify command - NEW (manual verification for admins)
    @app_commands.command(name="verify", description="Manually verify a user")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        user="User to verify",
        role="Role to assign after verification"
    )
    async def manual_verify(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        role: Optional[discord.Role] = None
    ):
        """Manually verify a user"""
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            
            # Create user data for API
            user_data = {
                'discord_id': str(user.id),
                'username': str(user),
                'access_token': 'manual_verification',
                'refresh_token': 'manual_verification',
                'expires_in': 604800,  # 7 days
                'guild_id': str(interaction.guild.id),
                'metadata': {
                    'manual': True,
                    'verified_by': str(interaction.user),
                    'avatar': str(user.avatar.url) if user.avatar else None
                }
            }
            
            # Send to API
            async with self.session.post(
                f"{self.bot.api_url}/api/bot/verify-manual",
                json=user_data
            ) as resp:
                if resp.status != 200:
                    await interaction.followup.send(
                        "❌ Failed to register verification with API.",
                        ephemeral=True
                    )
                    return
            
            # Assign role if specified
            if role:
                try:
                    await user.add_roles(role, reason=f"Manually verified by {interaction.user}")
                except Exception as e:
                    logger.error(f"Failed to assign role: {e}")
            
            # Mark as restored in API
            payload = {
                'member_ids': [str(user.id)],
                'role_id': str(role.id) if role else None
            }
            
            async with self.session.post(
                f"{self.bot.api_url}/api/bot/guild/{interaction.guild.id}/restore",
                json=payload
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to mark as restored: {await resp.text()}")
            
            embed = discord.Embed(
                title="✅ User Verified",
                description=f"Successfully verified {user.mention}",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            
            if role:
                embed.add_field(name="Role Assigned", value=role.mention)
            
            embed.set_footer(text=f"Verified by {interaction.user}")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Manual verify error: {e}")
            await interaction.followup.send(
                f"❌ Failed to verify user: {str(e)}",
                ephemeral=True
            )

# Setup and run bot
async def main():
    bot = VerificationBot()
    
    # Add cog
    await bot.add_cog(VerificationCog(bot))
    
    # Run bot
    await bot.start(DISCORD_BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
