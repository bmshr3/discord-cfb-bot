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
CHANNEL_ID = 1289678925055660084  # Replace if needed

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# Helper: Fetch ESPN scoreboard
async def fetch_espn_scoreboard():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    async with ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()

# Helper: Fetch AP rankings
async def fetch_ap_rankings():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings"
    async with ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()

# === ON READY ===
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Sync failed: {e}")

# === /cfbscore team:Alabama (PUBLIC, NO DEFER) ===
@tree.command(name="cfbscore", description="Check the live or final score of a specific FBS team.")
async def cfbscore(interaction: discord.Interaction, team: str):
    # No defer — send immediately (fast fetch)
    try:
        data = await asyncio.wait_for(fetch_espn_scoreboard(), timeout=5.0)  # Shorter timeout
        games = data.get("events", [])

        for game in games:
            competition = game["competitions"][0]
            competitors = competition["competitors"]
            home = competitors[0]
            away = competitors[1]

            if team.lower() in home["team"]["displayName"].lower() or team.lower() in away["team"]["displayName"].lower():
                home_name = home["team"]["displayName"]
                away_name = away["team"]["displayName"]
                home_score = home.get("score", "0")
                away_score = away.get("score", "0")
                status = competition["status"]["type"]["description"]

                embed = discord.Embed(
                    title=f"{away_name} @ {home_name}",
                    description=f"**{away_score} - {home_score}** ({status})",
                    color=discord.Color.blue(),
                )
                embed.set_footer(text="Data from ESPN")
                await interaction.response.send_message(embed=embed)  # Immediate, public
                return

        await interaction.response.send_message("No current or recent game found for that team.")

    except asyncio.TimeoutError:
        await interaction.response.send_message("ESPN is slow — try again in a minute.")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}")

# === /cfbboard ===
@tree.command(name="cfbboard", description="View all FBS games for today (Final, Live, Upcoming).")
async def cfbboard(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        data = await asyncio.wait_for(fetch_espn_scoreboard(), timeout=10.0)
        games = data.get("events", [])

        if not games:
            await interaction.followup.send("No FBS games found today.", ephemeral=True)
            return

        today = datetime.utcnow().strftime("%B %d, %Y")
        embed = discord.Embed(
            title=f"College Football Scoreboard – {today}",
            color=discord.Color.green(),
        )

        for game in games:
            competition = game["competitions"][0]
            competitors = competition["competitors"]
            status = competition["status"]["type"]["description"]
            date_str = competition.get("date", "")
            start_time = ""
            if date_str:
                try:
                    start_time = datetime.fromisoformat(date_str.replace("Z", "+00:00")).strftime("%I:%M %p ET")
                except:
                    start_time = "Time TBD"

            home = competitors[0]
            away = competitors[1]

            home_team = home["team"]["displayName"]
            away_team = away["team"]["displayName"]
            home_score = home.get("score", "0")
            away_score = away.get("score", "0")

            emoji = "Final" in status and "Final" or ("in" in status.lower() or "q" in status.lower()) and "Live" or "Upcoming"

            value = f"{away_score} - {home_score} ({status if 'TBD' not in status else start_time})"
            embed.add_field(name=f"{emoji} {away_team} @ {home_team}", value=value, inline=False)

        embed.set_footer(text="Includes late-night and upcoming games | Data via ESPN")
        await interaction.followup.send(embed=embed, ephemeral=True)

    except asyncio.TimeoutError:
        await interaction.followup.send("ESPN is taking too long — try again soon.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

# === /cfbrankings (FIXED) ===
@tree.command(name="cfbrankings", description="Show the latest AP Top 25 college football rankings.")
async def cfbrankings(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    try:
        data = await asyncio.wait_for(fetch_ap_rankings(), timeout=10.0)
        polls = data.get("rankings", [])
        ap_poll = next((p for p in polls if "AP Top 25" in p.get("name", "")), None)

        if not ap_poll:
            await interaction.followup.send("Could not fetch AP Top 25 rankings.", ephemeral=True)
            return

        embed = discord.Embed(title="AP Top 25 Rankings", color=discord.Color.gold())

        for team in ap_poll["ranks"][:25]:
            rank = team["current"]
            school = team["team"]["displayName"]  # ← FIXED: displayName, not displayname
            record = team.get("recordSummary", "—")
            embed.add_field(name=f"{rank}. {school}", value=record, inline=False)

        embed.set_footer(text="Data from ESPN")
        await interaction.followup.send(embed=embed, ephemeral=True)

    except asyncio.TimeoutError:
        await interaction.followup.send("Rankings are slow to load — try again.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)

# === ERROR HANDLER ===
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    await interaction.followup.send(f"Command failed: {error}", ephemeral=True)

# === RUN BOT ===
bot.run(DISCORD_TOKEN)
