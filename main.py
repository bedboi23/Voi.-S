import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
import os
import time

# --- CONFIGURATION ---
TOKEN = os.getenv("TOKEN") 

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Required to see your voice state
bot = commands.Bot(command_prefix="!", intents=intents)

queues = {}
now_playing = {}

# --- YTDL SOURCE CLASS ---
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title", "Unknown Track")
        self.duration = data.get("duration", 0)
        self.thumbnail = data.get("thumbnail")
        self.uploader = data.get("uploader", "Unknown Artist")

# --- YTDL + FFMPEG OPTIONS ---
ytdl_format_options = {
    "format": "bestaudio/best",
    "restrictfilenames": True,
    "noplaylist": True,
    "quiet": True,
    "default_search": "auto",
    "source_address": "0.0.0.0", 
}

ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

# --- HELPER FUNCTIONS ---
def create_progress_bar(current, total, length=20):
    if total <= 0: return "🔵" + "─" * (length - 1)
    percent = min(current / total, 1)  
    filled = int(percent * length)  
    bar = "─" * filled + "🔵" + "─" * max(0, length - filled - 1)  
    return bar

def format_time(seconds):
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"

def create_now_playing_embed(player, current_pos, total_duration):
    bar = create_progress_bar(current_pos, total_duration)
    current_time = format_time(current_pos)
    total_time = format_time(total_duration)

    embed = discord.Embed(title="🎵 Now Playing", color=0x5865F2)  
    embed.add_field(
        name="Track Info",  
        value=f"**{player.title[:45]}**\n🎨 Artist: **{player.uploader[:25]}**",
        inline=False
    )  
    embed.description = f"`{bar}`\n{current_time} / {total_time}"  

    if player.thumbnail:  
        embed.set_thumbnail(url=player.thumbnail)  
    embed.set_footer(text="Yukihana Music")  
    return embed

# --- BOT EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online!")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"❌ Sync error: {e}")

async def play_next(guild):
    if guild.id not in queues or not queues[guild.id]:
        now_playing.pop(guild.id, None)
        return

    vc = guild.voice_client
    if not vc: return

    player = queues[guild.id].pop(0)

    def after_playing(error):
        if error: print(f"Playback error: {error}")
        asyncio.run_coroutine_threadsafe(play_next(guild), bot.loop)

    vc.play(player, after=after_playing)

    if guild.id in now_playing:
        now_playing[guild.id]["player"] = player
        now_playing[guild.id]["start_time"] = time.time()
        asyncio.create_task(animate_progress(guild, player))

async def animate_progress(guild, player):
    try:
        while guild.id in now_playing and guild.voice_client and guild.voice_client.is_playing():
            data = now_playing[guild.id]
            elapsed = time.time() - data["start_time"]
            embed = create_now_playing_embed(player, elapsed, player.duration)
            await data["message"].edit(embed=embed)
            await asyncio.sleep(5) 
    except Exception:
        pass

# --- UPDATED PLAY COMMAND ---
@bot.tree.command(name="play", description="Play a song from YouTube")
async def play(interaction: discord.Interaction, query: str):
    if not interaction.user.voice:
        return await interaction.response.send_message("❌ Join a voice channel first!", ephemeral=True)

    await interaction.response.defer()

    try:
        # FIX: Force cleanup of existing ghost connections
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect(force=True)
            await asyncio.sleep(1)

        # FIX: Increased timeout to 60s for high-latency handshakes
        # Replace your connect line with this:
vc = await interaction.user.voice.channel.connect(timeout=60.0, self_deaf=True)


        if interaction.guild.id not in queues:
            queues[interaction.guild.id] = []

        search_query = f"ytsearch1:{query}" if not query.startswith("http") else query
        
        data = await bot.loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=False))
        if "entries" in data: data = data["entries"][0]

        # PCMVolumeTransformer requires ffmpeg, which is now in your nixpacks.toml
        player = YTDLSource(discord.FFmpegPCMAudio(data["url"], **ffmpeg_options), data=data)
        queues[interaction.guild.id].append(player)

        if not vc.is_playing():
            embed = create_now_playing_embed(player, 0, player.duration)
            msg = await interaction.followup.send(embed=embed)
            now_playing[interaction.guild.id] = {"message": msg, "player": player, "start_time": time.time()}
            await play_next(interaction.guild)
        else:
            await interaction.followup.send(f"✅ Added to queue: **{player.title}**")

    except asyncio.TimeoutError:
        await interaction.followup.send("❌ Voice handshake timed out. Please set your Discord Voice Region to 'US East'!")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}")

@bot.tree.command(name="stop", description="Stop music")
async def stop(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc:
        queues[interaction.guild.id] = []
        now_playing.pop(interaction.guild.id, None)
        await vc.disconnect()
        await interaction.response.send_message("⏹️ Stopped")
    else:
        await interaction.response.send_message("❌ Not in voice", ephemeral=True)

bot.run(TOKEN)
