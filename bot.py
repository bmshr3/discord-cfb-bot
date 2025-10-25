import os
import asyncio
import aiohttp
import discord
import json
from discord import app_commands, Embed
from datetime import datetime, timezone
from dotenv import load_dotenv

# ================================
# CONFIG
# ================================
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = 1289678925055660084
CHECK_INTERVAL = 120  # seconds between scoreboard checks
PERSIST_FILE = "last_states.json"

# ESPN College Football FBS endpoint
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
FBS_GROUP = "80"  # ESPN group ID for FBS

# Discord setup
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Track which games have already been announced
last_states = {}

# ------------------------------------
def load_states():
    global last_states
    if os.path.exists(PERSIST_FILE):
        try:
            with open(PERSIST_FILE, "r", encoding="utf-8") as f:
                last_states = json.load(f)
        except Exception:
            pass


def save_states():
    try:
        with open(PERSIST_FILE, "w", encoding="utf-8") as f:
            json.dump(last_states, f)
    except Exception as e:
        print("Error saving states:", e)


# ------------------------------------
async def fetch_espn(session, team=None, date=None):
    params = {"groups": FBS_GROUP}
    params["dates"] = date or datetime.now().strftime("%Y%m%d")

    async with session.get(ESPN_BASE, params=params, timeout=20) as r:
        r.raise_for_status()
        data = await r.json()

    events = data.get("events", [])
    if team:
        team_lower = team.lower()
        filtered = []
        for e in events:
            comp = e.get("competitions", [])[0]
            for c in comp.get("competitors", []):
                name = c.get("team", {}).get("displayName", "").lower()
                if team_lower in name:
                    filtered.append(e)
                    break
        return filtered
    return events


def parse_event(event):
    comp = event.get("competitions", [])[0]
    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    status = event.get("status", {})
    stype = status.get("type", {})

    return {
        "id": str(event.get("id")),
        "home_team": home.get("team", {}).get("displayName"),
        "away_team": away.get("team", {}).get("displayName"),
        "home_score": int(home.get("score") or 0),
        "away_score": int(away.get("score") or 0),
        "home_logo": home.get("team", {}).get("logo"),
        "away_logo": away.get("team", {}).get("logo"),
        "state": stype.get("state"),  # "pre", "in", or "post"
        "status_text": stype.get("description") or status.get("detail", ""),
        "clock": status.get("displayClock", ""),
        "period": status.get("period", 0),
        "venue": comp.get("venue", {}).get("fullName", ""),
        "link": comp.get("links", [{}])[0].get("href"),
    }


def make_embed(game):
    title = f"{game['away_team']} @ {game['home_team']}"
    desc = (
        f"**{game['away_team']}** — {game['away_score']}\n"
        f"**{game['home_team']}** — {game['home_score']}\n\n"
        f"**Status:** {game['status_text']}"
    )

    if game["state"] == "in":
        desc += f"\n**Q{game['period']} • {game['clock']}**"

    e = Embed(title=title, description=desc, timestamp=datetime.now(timezone.utc))
    if game.get("venue"):
        e.add_field(name="Venue", value=game["venue"], inline=False)
    if game.get("link"):
        e.add_field(name="ESPN", value=f"[Game Link]({game['link']})", inline=False)
    if game.get("home_logo"):
        e.set_thumbnail(url=game["home_logo"])
    return e


# ===================================
# BACKGROUND LOOP: ONLY POSTS FINAL SCORES
# ===================================
async def scoreboard_loop():
    await client.wait_until_ready()
    if not CHANNEL_ID:
        print("CHANNEL_ID not configured")
        return

    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print("Channel not found.")
        return

    async with aiohttp.ClientSession() as session:
        while not client.is_closed():
            try:
                today = datetime.now().strftime("%Y%m%d")
                events = await fetch_espn(session, date=today)

                for e in events:
                    g = parse_event(e)
                    gid = g["id"]
                    # Only post games that have just gone final ("post" state)
                    if g["state"] == "post" and gid not in last_states:
                        await channel.send(embed=make_embed(g))
                        last_states[gid] = "posted"
                        save_states()

            except Exception as err:
                print("Loop error:", err)

            await asyncio.sleep(CHECK_INTERVAL)


# ===================================
# SLASH COMMAND: /cfbscore <team>
# ===================================
@tree.command(name="cfbscore", description="Get current or upcoming game for a specific FBS team")
async def cfbscore(interaction: discord.Interaction, team: str):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        events = await fetch_espn(session, team=team)
        if not events:
            await interaction.followup.send(f"No FBS game found for **{team}** today.")
            return

        g = parse_event(events[0])
        embed = make_embed(g)
        await interaction.followup.send(embed=embed)


@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user} — Slash commands synced.")
    client.loop.create_task(scoreboard_loop())


if __name__ == "__main__":
    load_states()
    if not DISCORD_TOKEN or CHANNEL_ID == 0:
        print("Missing DISCORD_TOKEN or CHANNEL_ID.")
    else:
        client.run(DISCORD_TOKEN)
