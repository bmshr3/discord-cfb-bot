import os
import discord
from discord.ext import commands
from aiohttp import ClientSession
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1289678925055660084

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

# Helper function to get today's ESPN scoreboard
async def fetch_espn_scoreboard():
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    async with ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.json()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

# 🏈 /cfbscore <team> — check one team’s game
@bot.slash_command(name="cfbscore", description="Check the live or final score of a specific FBS team.")
async def cfbscore(ctx, team: str):
    await ctx.defer(ephemeral=True)  # private response
    data = await fetch_espn_scoreboard()
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
            await ctx.respond(embed=embed, ephemeral=True)
            return

    await ctx.respond("❌ No current or recent game found for that team.", ephemeral=True)

# 🗓️ /cfbboard — show today’s full FBS scoreboard
@bot.slash_command(name="cfbboard", description="View all FBS games for today (Final, Live, Upcoming).")
async def cfbboard(ctx):
    await ctx.defer(ephemeral=True)
    data = await fetch_espn_scoreboard()
    games = data.get("events", [])

    if not games:
        await ctx.respond("No FBS games found today.", ephemeral=True)
        return

    today = datetime.utcnow().date()
    embed = discord.Embed(
        title=f"🏈 College Football Scoreboard – {today.strftime('%B %d, %Y')}",
        color=discord.Color.green(),
    )

    for game in games:
        competition = game["competitions"][0]
        competitors = competition["competitors"]
        status = competition["status"]["type"]["description"]
        date_str = competition.get("date")
        start_time = datetime.fromisoformat(date_str.replace("Z", "+00:00")).strftime("%I:%M %p ET")

        home = competitors[0]
        away = competitors[1]

        home_team = home["team"]["displayName"]
        away_team = away["team"]["displayName"]
        home_score = home.get("score", "0")
        away_score = away.get("score", "0")

        # status emoji
        if "Final" in status:
            emoji = "✅"
        elif "in" in status or "Q" in status:
            emoji = "🔴"
        else:
            emoji = "⏰"

        embed.add_field(
            name=f"{emoji} {away_team} @ {home_team}",
            value=f"{away_score} - {home_score} ({status if 'TBD' not in status else start_time})",
            inline=False,
        )

    embed.set_footer(text="Includes late-night and upcoming games | Data via ESPN")
    await ctx.respond(embed=embed, ephemeral=True)

# 🏆 /cfbrankings — show the AP Top 25
@bot.slash_command(name="cfbrankings", description="Show the latest AP Top 25 college football rankings.")
async def cfbrankings(ctx):
    await ctx.defer(ephemeral=True)
    url = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings"
    async with ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()

    polls = data.get("rankings", [])
    ap_poll = next((p for p in polls if "AP Top 25" in p["name"]), None)

    if not ap_poll:
        await ctx.respond("❌ Could not fetch AP Top 25 rankings.", ephemeral=True)
        return

    embed = discord.Embed(title="🏆 AP Top 25 Rankings", color=discord.Color.gold())

    for team in ap_poll["ranks"]:
        rank = team["current"]
        school = team["team"]["displayName"]
        record = team.get("recordSummary", "")
        embed.add_field(name=f"{rank}. {school}", value=record, inline=False)

    embed.set_footer(text="Data from ESPN")
    await ctx.respond(embed=embed, ephemeral=True)

bot.run(DISCORD_TOKEN)
