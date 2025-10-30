import os
import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import ClientSession
from datetime import datetime, timezone
from dotenv import load_dotenv
import asyncio
import json  # For safe parsing

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CFBD_API_KEY = os.getenv("CFBD_API_KEY")  # ← Your new API key
CHANNEL_ID = 1289678925055660084  # Your channel
GUILD_ID = 1204169619112464404  # ← Replace with your Discord server ID for fast sync

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# Helper: Fetch CFBD games (scoreboard)
async def fetch_cfbd_games(year=None, season_type="regular"):
    if not year:
        year = datetime.now(timezone.UTC).year
    url = f"https://api.collegefootballdata.com/games"
    params = {"year": year, "season_type": season_type}
    headers = {"Authorization": f"Bearer {CFBD_API_KEY}"}
    async with ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 401:
                raise ValueError("Invalid CFBD API key — check env var")
            return await resp.json()

# Helper: Fetch CFBD rankings
async def fetch_cfbd_rankings(year=None, week=None, poll="AP"):
    if not year:
        year = datetime.now(timezone.UTC).year
    if not week:
        week = get_current_week(year)  # Define below
    url = "https://api.collegefootballdata.com/rankings"
    params = {"year": year, "week": week, "poll": poll}
    headers = {"Authorization": f"Bearer {CFBD_API_KEY}"}
    async with ClientSession() as session:
        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 401:
                raise ValueError("Invalid CFBD API key — check env var")
            return await resp.json()

# Helper: Get current week (rough estimate)
def get_current_week(year):
    now = datetime.now(timezone.UTC)
    if now.month < 9:
        return 1  # Off-season
    week = max(1, min(15, int((now - datetime(year, 9, 1, tzinfo=timezone.UTC)).days / 7) + 1))
    return week

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

# === AUTO-POST FINAL SCORES (Updated for CFBD) ===
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
                status = game.get("status", {}).get("type", {}).get("description", "")
                home = game.get("home_team", {})
                away = game.get("away_team", {})

                if "completed" in status.lower() and game_id not in final_games:  # CFBD uses "completed"
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

# === /cfbscore team:Alabama (PUBLIC, NO DEFER) ===
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

        await interaction.response.send_message("No current or recent game found for that team.")

    except asyncio.TimeoutError:
        await interaction.response.send_message("CFBD is slow — try again in a minute.")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}")

# === /cfbboard ===
@tree.command(name="cfbboard", description="View all FBS games for today (Final, Live, Upcoming).")
async def cfbboard(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        games = await asyncio.wait_for(fetch_cfbd_games(), timeout=10.0)
        if not games:
            await interaction.followup.send("No FBS games found.", ephemeral=True)
            return

        today = datetime.now(timezone.UTC).strftime("%B %d, %Y")
        embed = discord.Embed(
            title=f"College Football Scoreboard – {today}",
            color=discord.Color.green(),
        )

        for game in games[:20]:  # Limit to recent/relevant
            home = game.get("home_team", {})
            away = game.get("away_team", {})
            home_name = home.get("school", "Unknown")
            away_name = away.get("school", "Unknown")
            home_score = str(game.get("home_points", 0))
            away_score = str(game.get("away_points", 0))
            status = game.get("status", {}).get("type", {}).get("description", "Scheduled")

            emoji = "Final" if "completed" in status.lower() else "Live" if "in progress" in status.lower() else "Upcoming"
            value = f"{away_score} - {home_score} ({status})"
            embed.add_field(name=f"{emoji} {away_name} @ {home_name}", value=value, inline=False)

        embed.set_footer(text="Data from CFBD")
        await interaction.followup.send(embed=embed, ephemeral=True)

    except asyncio.TimeoutError:
        await interaction.followup.send("CFBD is taking too long — try again soon.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

# === /cfbrankings ===
@tree.command(name="cfbrankings", description="Show the latest AP Top 25 college football rankings.")
async def cfbrankings(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        rankings = await asyncio.wait_for(fetch_cfbd_rankings(), timeout=10.0)
        if not rankings:
            await interaction.followup.send("Could not fetch AP Top 25 rankings.", ephemeral=True)
            return

        embed = discord.Embed(title="AP Top 25 Rankings", color=discord.Color.gold())

        for rank_item in rankings[:25]:
            rank = rank_item.get("rank", "?")
            school = rank_item.get("school", "Unknown")
            record = rank_item.get("record", "—")
            embed.add_field(name=f"{rank}. {school}", value=record, inline=False)

        embed.set_footer(text="Data from CFBD")
        await interaction.followup.send(embed=embed, ephemeral=True)

    except asyncio.TimeoutError:
        await interaction.followup.send("Rankings are slow to load — try again.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

# === ERROR HANDLER ===
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if not interaction.response.is_done():
        await interaction.response.send_message(f"Command failed: {error}", ephemeral=True)

# === RUN BOT ===
bot.run(DISCORD_TOKEN)