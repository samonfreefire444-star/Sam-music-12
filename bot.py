import os
import sys
import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
from flask import Flask
from threading import Thread

# Flask App for 24/7 Hosting
app = Flask('')

@app.route('/')
def home():
    return "SAM MUSIC IS ALIVE!"

def run():
    # Render-ൽ പോർട്ട് ഓട്ടോമാറ്റിക്കായി ലഭിക്കാൻ os.getenv ഉപയോഗിക്കുന്നു
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger("sam_music")

try:
    if not discord.opus.is_loaded():
        discord.opus.load_opus("libopus.so.0")
except Exception:
    try:
        discord.opus.load_opus("libopus.so")
    except Exception:
        pass

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

YTDL_FORMAT_OPTS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'geo_bypass': True,
}

FFMPEG_OPTS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn',
}

class Song:
    def __init__(self, title, webpage_url, duration, thumbnail, requester=None):
        self.title = title
        self.webpage_url = webpage_url
        self.duration = duration
        self.thumbnail = thumbnail
        self.requester = requester

    @property
    def duration_str(self):
        if self.duration:
            m, s = divmod(int(self.duration), 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
        return "Live"

    async def get_stream_url(self):
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YTDL_FORMAT_OPTS) as ytdl:
            info = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(self.webpage_url, download=False)
            )
            if info and 'entries' in info:
                info = info['entries'][0]
            return info.get('url') if info else None

class MusicPlayer:
    def __init__(self):
        self.queue = []
        self.current = None
        self.loop_mode = "off"
        self.text_channel = None
        self.voice_client = None

    def clear(self):
        self.queue.clear()
        self.current = None
        self.loop_mode = "off"

players = {}

def get_player(guild_id):
    if guild_id not in players:
        players[guild_id] = MusicPlayer()
    return players[guild_id]

async def search_yt(query):
    loop = asyncio.get_event_loop()
    if query.startswith(('http://', 'https://')):
        search = query
    else:
        search = f"ytsearch:{query}"
    with yt_dlp.YoutubeDL(YTDL_FORMAT_OPTS) as ytdl:
        try:
            info = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(search, download=False)
            )
            if not info:
                return None
            if 'entries' in info:
                info = info['entries'][0]
            if not info:
                return None
            return Song(
                title=info.get('title', 'Unknown'),
                webpage_url=info.get('webpage_url') or info.get('original_url') or query,
                duration=info.get('duration', 0),
                thumbnail=info.get('thumbnail', ''),
            )
        except Exception as e:
            log.error(f"Search error: {e}")
            return None

def embed_now_playing(song):
    e = discord.Embed(
        title="🎵 ഇപ്പോൾ play ആകുന്നത്",
        description=f"**[{song.title}]({song.webpage_url})**",
        color=discord.Color.from_rgb(255, 87, 51),
    )
    e.add_field(name="⏱️ ദൈർഘ്യം", value=song.duration_str, inline=True)
    if song.requester:
        e.add_field(name="🎧 Request ചെയ്തത്", value=song.requester.mention, inline=True)
    if song.thumbnail:
        e.set_thumbnail(url=song.thumbnail)
    e.set_footer(text="🎶 SAM MUSIC • Malayalam")
    return e

class Controls(discord.ui.View):
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="⏯️ Play/Pause", style=discord.ButtonStyle.primary)
    async def toggle(self, interaction, _):
        vc = get_player(self.guild_id).voice_client
        if not vc or not vc.is_connected():
            return await interaction.response.send_message("❌ VC-ൽ ഇല്ല!", ephemeral=True)
        if vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resume!", ephemeral=True)
        elif vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Pause!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Play ആകുന്നില്ല!", ephemeral=True)

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction, _):
        vc = get_player(self.guild_id).voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Play ആകുന്നില്ല!", ephemeral=True)

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction, _):
        p = get_player(self.guild_id)
        if p.voice_client and p.voice_client.is_connected():
            p.clear()
            p.voice_client.stop()
            await p.voice_client.disconnect()
            p.voice_client = None
            await interaction.response.send_message("⏹️ Stop!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ VC-ൽ ഇല്ല!", ephemeral=True)

async def play_next(guild_id):
    p = get_player(guild_id)
    vc = p.voice_client
    if not vc or not vc.is_connected():
        return

    if p.loop_mode == "single" and p.current:
        song = p.current
    elif p.queue:
        if p.loop_mode == "queue" and p.current:
            p.queue.append(p.current)
        song = p.queue.pop(0)
        p.current = song
    else:
        if p.loop_mode == "queue" and p.current:
            song = p.current
        else:
            p.current = None
            if p.text_channel:
                await p.text_channel.send(embed=discord.Embed(
                    title="📭 Queue അവസാനിച്ചു",
                    description="എല്ലാ ഗാനങ്ങളും play ആയി!",
                    color=discord.Color.orange(),
                ))
            return

    try:
        stream_url = await song.get_stream_url()
        if not stream_url:
            raise ValueError("Stream URL കിട്ടിയില്ല")

        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTS)
        source = discord.PCMVolumeTransformer(source, volume=0.8)

        def after_play(err):
            if err:
                log.error(f"Playback error: {err}")
            asyncio.run_coroutine_threadsafe(play_next(guild_id), bot.loop)

        vc.play(source, after=after_play)
        if p.text_channel:
            await p.text_channel.send(embed=embed_now_playing(song), view=Controls(guild_id))
    except Exception as e:
        log.error(f"play_next error: {e}")
        if p.text_channel:
            await p.text_channel.send(embed=discord.Embed(
                title="❌ Play error",
                description=f"**{song.title}**\n`{e}`",
                color=discord.Color.red(),
            ))
        if p.queue:
            p.current = p.queue.pop(0)
            await play_next(guild_id)

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        log.info(f"Logged in as {bot.user} | {len(synced)} commands synced | Opus: {discord.opus.is_loaded()}")
    except Exception as e:
        log.error(f"Sync failed: {e}")

@bot.tree.command(name="play", description="ഒരു ഗാനം play ചെയ്യുക")
@app_commands.describe(query="ഗാനത്തിന്റെ പേര് അല്ലെങ്കിൽ YouTube link")
async def play(interaction: discord.Interaction, query: str):
    try:
        await interaction.response.defer()
    except Exception:
        return

    if not interaction.user.voice or not interaction.user.voice.channel:
        return await interaction.followup.send(embed=discord.Embed(
            title="❌ Voice Channel!",
            description="ആദ്യം ഒരു **voice channel-ൽ join** ചെയ്യൂ!",
            color=discord.Color.red(),
        ), ephemeral=True)

    p = get_player(interaction.guild_id)
    p.text_channel = interaction.channel
    vc_channel = interaction.user.voice.channel

    try:
        if not p.voice_client or not p.voice_client.is_connected():
            p.voice_client = await vc_channel.connect()
        elif p.voice_client.channel.id != vc_channel.id:
            await p.voice_client.move_to(vc_channel)
    except Exception as e:
        return await interaction.followup.send(embed=discord.Embed(
            title="❌ VC Error", description=f"`{e}`", color=discord.Color.red()))

    song = await search_yt(query)
    if not song:
        return await interaction.followup.send(embed=discord.Embed(
            title="❌ കണ്ടെത്തിയില്ല",
            description="ഗാനം കണ്ടെത്തിയില്ല. മറ്റൊരു query try ചെയ്യൂ.",
            color=discord.Color.red(),
        ))

    song.requester = interaction.user
    vc = p.voice_client

    if vc.is_playing() or vc.is_paused():
        p.queue.append(song)
        e = discord.Embed(title="📥 Queue-ൽ ചേർത്തു",
                          description=f"**[{song.title}]({song.webpage_url})**",
                          color=discord.Color.green())
        e.add_field(name="ദൈർഘ്യം", value=song.duration_str, inline=True)
        e.add_field(name="Position", value=f"#{len(p.queue)}", inline=True)
        if song.thumbnail:
            e.set_thumbnail(url=song.thumbnail)
        e.set_footer(text="🎶 SAM MUSIC • Malayalam")
        await interaction.followup.send(embed=e)
    else:
        p.current = song
        await interaction.followup.send(embed=discord.Embed(
            title="🔍 Loading...", description=f"**{song.title}**", color=discord.Color.orange()
        ))
        await play_next(interaction.guild_id)

@bot.tree.command(name="skip", description="ഇപ്പോഴത്തെ ഗാനം skip")
async def skip(interaction: discord.Interaction):
    vc = get_player(interaction.guild_id).voice_client
    if not vc or not (vc.is_playing() or vc.is_paused()):
        return await interaction.response.send_message("❌ Play ആകുന്നില്ല!", ephemeral=True)
    vc.stop()
    await interaction.response.send_message(embed=discord.Embed(title="⏭️ Skip!", color=discord.Color.blurple()))

# ബോട്ട് റൺ ചെയ്യുന്ന ഭാഗം
if __name__ == "__main__":
    # Render-ൽ Variables ടാബിൽ TOKEN എന്ന് തന്നെ നൽകുക
    token = os.environ.get("TOKEN")
    if token:
        keep_alive() # Flask സർവർ സ്റ്റാർട്ട് ചെയ്യുന്നു
        bot.run(token)
    else:
        log.error("TOKEN കണ്ടെത്തിയില്ല! Render settings പരിശോധിക്കുക.")
