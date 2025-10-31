import os
import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import ClientSession
from datetime import datetime
from dotenv import load_dotenv
import asyncio

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CFBD_API_KEY = os.getenv("CFBD_API_KEY")  # Your CFBD key
CHANNEL_ID = 1289678925055660084  # Your channel
GUILD_ID = 1204169619112464404  # ← REPLACE with your Discord server ID (right-click server → Copy ID)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# Helper: Fetch CFBD games (FBS only, filter for today/upcoming — FIXED date match)
async def fetch_cfbd_games(year=None, season_type="regular"):
    if not year:
        year = datetime.utcnow().year
    url = f"https://api.collegefootballdata.com/games"
    params = {"year": year, "season_type": season_type, "division": "fbs"}
    headers = {"Authorization": f"Bearer {CFBD_API_KEY}"}
    async with ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 401:
                raise ValueError("Invalid CFBD API key — check env var")
            data = await resp.json()
            # Filter for games starting today or later — FIXED: Parse date only
            today = datetime.utcnow().date()
            recent_games = []
            for g in data:
                start_date_str = g.get("start_date", "")
                if start_date_str:
                    try:
                        # Parse full ISO timestamp, compare dates only
                        game_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00')).date()
                        if game_date >= today:
                            recent_games.append(g)
                    except ValueError:
                        pass  # Skip invalid dates
            # Sort by start_date (newest first — prioritizes live/upcoming)
            recent_games.sort(key=lambda g: g.get("start_date", "2025-01-01"), reverse=True)
            return recent_games

# === ON READY ===
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        # Fast sync to your guild (instant) + global (1hr)
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            await tree.sync(guild=guild)
            print(f"Synced {len(await tree.fetch_guild_commands(guild))} commands to guild {GUILD_ID}")
        await tree.sync()  # Global sync
        print(f"Synced {len(await tree.fetch_global_commands())} global commands")
    except Exception as e:
        print(f"Sync failed: {e}")

    # Start auto-posting final scores
    bot.loop.create_task(monitor_final_scores())
    print("Final score monitor started")

# === AUTO-POST FINAL SCORES (CFBD) ===
final_games = set()  # Track posted game IDs

async def monitor_final_scores():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"ERROR: Channel {CHANNEL_ID} not found! Check ID and bot permissions.")
        return
    else:
        print(f"Auto-posting to: #{channel.name} in {channel.guild.name}")

    await bot.wait_until_ready()
    print("Final score monitor is running...")

    while not bot.is_closed():
        try:
            games = await fetch_cfbd_games()
            for game in games:
                game_id = game["id"]
                status = game.get("status", {}).get("type", {}).get("description", "").lower()
                home = game.get("home_team", {})
                away = game.get("away_team", {})

                if "completed" in status and game_id not in final_games:
                    home_name = home.get("school", "Unknown")
                    away_name = away.get("school", "Unknown")
                    home_score = str(game.get("home_points", 0))
                    away_score = str(game.get("away_points", 0))

                    embed = discord.Embed(
                        title=f"FINAL: {away_name} @ {home_name}",
                        description=f"**{away_score} – {home_score}**",
                        color=discord.Color.red(),
                    )
                    embed.set_footer(text="Data from CFBD")
                    await channel.send(embed=embed)

                    final_games.add(game_id)
                    print(f"Posted final: {away_name} @ {home_name}")

        except Exception as e:
            print(f"Final monitor error: {e}")

        await asyncio.sleep(60)  # Check every minute

# === /cfbscore team:UTSA (PUBLIC, NO DEFER) ===
@tree.command(name="cfbscore", description="Check the live or final score of a specific FBS team.")
async def cfbscore(interaction: discord.Interaction, team: str):
    try:
        games = await asyncio.wait_for(fetch_cfbd_games(), timeout=5.0)
        for game in games:
            home = game.get("home_team", {})
            away = game.get("away_team", {})
            if team.lower() in home.get("school", "").lower() or team.lower() in away.get("school", "").lower():
                home_name = home.get("school", "Unknown")
                away_name = away.get("school", "Unknown")
                home_score = str(game.get("home_points", 0))
                away_score = str(game.get("away_points", 0))
                status = game.get("status", {}).get("type", {}).get("description", "Unknown")

                embed = discord.Embed(
                    title=f"{away_name} @ {home_name}",
                    description=f"**{away_score} - {home_score}** ({status})",
                    color=discord.Color.blue(),
                )
                embed.set_footer(text="Data from CFBD")
                await interaction.response.send_message(embed=embed)  # Public
                return

        await interaction.response.send_message("No current or recent game found for that team. Try 'Tulane' for tonight's matchup.")

    except asyncio.TimeoutError:
        await interaction.response.send_message("CFBD is slow — try again in a minute.")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}")

# === ERROR HANDLER ===
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if not interaction.response.is_done():
        await interaction.response.send_message(f"Command failed: {error}", ephemeral=True)

# === RUN BOT ===
bot.run(DISCORD_TOKEN)