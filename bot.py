import os
import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import ClientSession
from datetime import datetime, timedelta
from dotenv import load_dotenv
import asyncio

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1289678925055660084  # Your channel
GUILD_ID = 1204169619112464404  # ← REPLACE with your Discord server ID (right-click server → Copy ID)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# Helper: Fetch ESPN scoreboard (full current week — includes all Thu-Sun games)
async def fetch_espn_scoreboard():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    async with ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()

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

# === AUTO-POST FINAL SCORES (ESPN) ===
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
            data = await fetch_espn_scoreboard()
            games = data.get("events", [])
            for game in games:
                game_id = game["id"]
                competition = game["competitions"][0]
                status = competition["status"]["type"]["description"].lower()
                competitors = competition["competitors"]
                home = competitors[0]
                away = competitors[1]

                if "final" in status and game_id not in final_games:
                    home_name = home["team"]["displayName"]
                    away_name = away["team"]["displayName"]
                    home_score = home.get("score", "0")
                    away_score = away.get("score", "0")

                    embed = discord.Embed(
                        title=f"FINAL: {away_name} @ {home_name}",
                        description=f"**{away_score} – {home_score}**",
                        color=discord.Color.red(),
                    )
                    embed.set_footer(text="Data from ESPN")
                    await channel.send(embed=embed)

                    final_games.add(game_id)
                    print(f"Posted final: {away_name} @ {home_name}")

        except Exception as e:
            print(f"Final monitor error: {e}")

        await asyncio.sleep(60)  # Check every minute

# === /cfbscore team:Alabama (PUBLIC, SHOWS SCHEDULED GAMES) ===
@tree.command(name="cfbscore", description="Check the live, final, or scheduled score of a specific FBS team.")
async def cfbscore(interaction: discord.Interaction, team: str):
    try:
        data = await asyncio.wait_for(fetch_espn_scoreboard(), timeout=5.0)
        games = data.get("events", [])
        for game in games:
            competition = game["competitions"][0]
            competitors = competition["competitors"]
            home = competitors[0]
            away = competitors[1]

            # Match team name
            if team.lower() in home["team"]["displayName"].lower() or team.lower() in away["team"]["displayName"].lower():
                home_name = home["team"]["displayName"]
                away_name = away["team"]["displayName"]
                home_score = home.get("score", "0")
                away_score = away.get("score", "0")
                status = competition["status"]["type"]["description"]

                # Format game time if scheduled
                game_time = ""
                if "Scheduled" in status:
                    try:
                        date_str = competition.get("date", "")
                        game_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        game_time = f" — {game_dt.strftime('%a, %I:%M %p ET')}"
                    except:
                        game_time = ""

                embed = discord.Embed(
                    title=f"{away_name} @ {home_name}",
                    description=f"**{away_score} - {home_score}** ({status}{game_time})",
                    color=discord.Color.blue(),
                )
                embed.set_footer(text="Data from ESPN")
                await interaction.response.send_message(embed=embed)  # Public
                return

        await interaction.response.send_message("No game found for that team this weekend.")

    except asyncio.TimeoutError:
        await interaction.response.send_message("ESPN is slow — try again in a minute.")
    except Exception as e:
        await interaction.response.send_message(f"Error: {e}")

# === ERROR HANDLER ===
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if not interaction.response.is_done():
        await interaction.response.send_message(f"Command failed: {error}", ephemeral=True)

# === RUN BOT ===
bot.run(DISCORD_TOKEN)