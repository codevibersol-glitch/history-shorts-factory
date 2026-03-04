#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                     🏛️  HISTORY SHORTS FACTORY  🏛️                            ║
║           Production-Grade YouTube Shorts Generator for History Content       ║
╚═══════════════════════════════════════════════════════════════════════════════╝

A fully automatic CLI tool that generates engaging 45-60 second YouTube Shorts
about history, wars, battles, and interesting facts.

Features:
  • Grok API script writing (grok-4-1-fast-reasoning)
  • Grok Imagine Video API for cinematic 9:16 clips
  • Professional TTS with edge-tts
  • Daily automation mode
  • Beautiful live terminal UI

Usage:
  python history_shorts.py run --topic "World War II" --use-grok-imagine
  python history_shorts.py run --verbose --use-grok-imagine
"""

from __future__ import annotations

# =============================================================================
# IMPORTS
# =============================================================================

import os
import sys
import re
import json
import time
import random
import tempfile
import shutil
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
from dataclasses import dataclass, field

# CLI & UI
import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TaskProgressColumn,
    Live,
)
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.logging import RichHandler
from rich import box

# Logging
from loguru import logger

# Content & Research
import wikipedia
from wikipedia.exceptions import DisambiguationError, PageError

# Text-to-Speech
import edge_tts
from edge_tts import VoicesManager

# Video Processing
from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    TextClip,
    CompositeAudioClip,
    ImageClip,
)
from moviepy.video.fx.all import fadein, fadeout
from PIL import Image, ImageDraw, ImageFont

# Retries & Resilience
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
)

# Environment
from dotenv import load_dotenv

# Grok Imagine Video API (xAI SDK)
try:
    from xai_sdk import Client as XAIClient
    XAI_AVAILABLE = True
except ImportError:
    XAI_AVAILABLE = False
    XAIClient = None

# HTTP
import requests
import aiohttp
import asyncio

# =============================================================================
# CONFIGURATION & CONSTANTS
# =============================================================================

# App metadata
APP_NAME = "History Shorts Factory"
APP_VERSION = "1.0.0"
APP_AUTHOR = "History Shorts Team"

# Video specifications (YouTube Shorts)
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
SHORTS_ASPECT_RATIO = "9:16"
MIN_DURATION = 45
MAX_DURATION = 60
DEFAULT_FPS = 30

# Subtitle styling
SUBTITLE_FONT_SIZE = 56
SUBTITLE_COLOR = "yellow"
SUBTITLE_OUTLINE_COLOR = "black"
SUBTITLE_OUTLINE_WIDTH = 3

# Font configuration - try common fonts with fallbacks
def get_available_font():
    """Get an available font for the system."""
    # Try common fonts in order of preference
    font_candidates = [
        "Arial-Bold",           # Windows/Linux
        "Helvetica-Bold",       # macOS
        "Helvetica",            # macOS fallback
        "Arial",                # Universal fallback
        "/System/Library/Fonts/Helvetica.ttc",  # macOS system path
        "/System/Library/Fonts/Arial.ttf",      # macOS system path
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
    ]
    return font_candidates[0]  # MoviePy will search system fonts

SUBTITLE_FONT = get_available_font()

# TTS defaults
DEFAULT_TTS_VOICE = "en-US-ChristopherNeural"
DEFAULT_TTS_RATE = "+0%"
DEFAULT_TTS_VOLUME = "+0%"

# Retry configuration
MAX_RETRIES = 3
RETRY_MIN_WAIT = 1.0
RETRY_MAX_WAIT = 10.0

# Paths
BASE_DIR = Path(__file__).parent.absolute()
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"
TEMP_DIR = BASE_DIR / "temp"
TOKEN_FILE = BASE_DIR / "token.json"

# Ensure directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# GLOBAL STATE
# =============================================================================

console = Console()
error_console = Console(stderr=True)

# Global flag for graceful shutdown
shutdown_requested = False

# Temporary files tracking for cleanup
temp_files: List[Path] = []

# =============================================================================
# ENVIRONMENT LOADING
# =============================================================================

load_dotenv(BASE_DIR / ".env")

# Configuration from environment
config = {
    "xai_api_key": os.getenv("XAI_API_KEY", ""),
    "default_topic": os.getenv("DEFAULT_TOPIC", "World War II"),
    "video_duration": int(os.getenv("VIDEO_DURATION", "55")),
    "tts_voice": os.getenv("TTS_VOICE", DEFAULT_TTS_VOICE),
    "tts_rate": os.getenv("TTS_RATE", DEFAULT_TTS_RATE),
    "tts_volume": os.getenv("TTS_VOLUME", DEFAULT_TTS_VOLUME),
    "video_resolution": os.getenv("VIDEO_RESOLUTION", "720p"),
    "video_fps": int(os.getenv("VIDEO_FPS", "30")),
    "subtitle_font_size": int(os.getenv("SUBTITLE_FONT_SIZE", "56")),
    "subtitle_color": os.getenv("SUBTITLE_COLOR", "yellow"),
    "subtitle_outline_color": os.getenv("SUBTITLE_OUTLINE_COLOR", "black"),
    "default_tags": os.getenv("DEFAULT_TAGS", "history,shorts,facts,educational"),
    "debug": os.getenv("DEBUG", "false").lower() == "true",
    "max_retries": int(os.getenv("MAX_RETRIES", "3")),
    "grok_script_model": os.getenv("GROK_SCRIPT_MODEL", "grok-4-1-fast-reasoning"),
}

# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure loguru with Rich handler and daily rotating file."""
    
    # Remove default handler
    logger.remove()
    
    # Log level
    level = "DEBUG" if verbose else ("WARNING" if quiet else "INFO")
    
    # Console handler with Rich
    if not quiet:
        logger.add(
            RichHandler(
                console=console,
                rich_tracebacks=True,
                tracebacks_show_locals=verbose,
                markup=True,
            ),
            format="{message}",
            level=level,
        )
    
    # Daily rotating file handler
    log_file = LOGS_DIR / f"history_shorts_{datetime.now().strftime('%Y%m%d')}.log"
    logger.add(
        log_file,
        rotation="00:00",
        retention="7 days",
        compression="zip",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )
    
    logger.info(f"📝 Logging to [cyan]{log_file}[/cyan]")

# =============================================================================
# SIGNAL HANDLERS & CLEANUP
# =============================================================================

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global shutdown_requested
    shutdown_requested = True
    console.print("\n[yellow]⚠️  Shutdown requested. Cleaning up...[/yellow]")
    cleanup_temp_files()
    sys.exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def cleanup_temp_files() -> None:
    """Remove all temporary files."""
    global temp_files
    for temp_file in temp_files:
        try:
            if temp_file.exists():
                temp_file.unlink()
                logger.debug(f"Cleaned up temp file: {temp_file}")
        except Exception as e:
            logger.warning(f"Failed to clean up {temp_file}: {e}")
    temp_files.clear()
    
    # Clean temp directory
    try:
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"Failed to clean temp directory: {e}")

@contextmanager
def temp_file(suffix: str = ".tmp", prefix: str = "history_shorts_"):
    """Context manager for temporary files with auto-cleanup."""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix=prefix, dir=TEMP_DIR)
    os.close(fd)
    temp_path = Path(path)
    temp_files.append(temp_path)
    try:
        yield temp_path
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        if temp_path in temp_files:
            temp_files.remove(temp_path)

# =============================================================================
# RETRY DECORATORS
# =============================================================================

def retry_decorator(max_attempts: int = MAX_RETRIES):
    """Standard retry decorator with exponential backoff."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=RETRY_MIN_WAIT, max=RETRY_MAX_WAIT),
        retry=retry_if_exception_type((requests.exceptions.RequestException, ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, "WARNING"),
        after=after_log(logger, "DEBUG"),
        reraise=True,
    )

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ScriptData:
    """Container for generated script data."""
    topic: str
    title: str
    narration: str
    facts: List[str]
    wikipedia_summary: str
    tags: List[str]
    estimated_duration: float = 55.0

@dataclass
class VideoAssets:
    """Container for generated video assets."""
    video_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    subtitle_path: Optional[Path] = None
    thumbnail_path: Optional[Path] = None
    duration: float = 0.0

# =============================================================================
# UI COMPONENTS
# =============================================================================

def create_startup_panel() -> Panel:
    """Create the beautiful startup panel."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", justify="right")
    table.add_column(style="white")
    
    table.add_row("📅 Date:", now)
    table.add_row("📁 Output:", str(OUTPUT_DIR))
    table.add_row("📝 Logs:", str(LOGS_DIR))
    table.add_row("🎬 Resolution:", f"{SHORTS_WIDTH}x{SHORTS_HEIGHT}")
    table.add_row("⏱️  Duration:", f"{MIN_DURATION}-{MAX_DURATION}s")
    
    panel = Panel(
        table,
        title="[bold cyan]🏛️  HISTORY SHORTS FACTORY[/bold cyan]",
        subtitle=f"[dim]v{APP_VERSION} • Production-Ready YouTube Shorts Generator[/dim]",
        box=box.DOUBLE_EDGE,
        border_style="cyan",
        padding=(1, 2),
    )
    return panel

def create_step_panel(step_num: int, step_name: str, status: str = "pending") -> Panel:
    """Create a step status panel."""
    status_icons = {
        "pending": "⏳",
        "running": "🔄",
        "completed": "✅",
        "failed": "❌",
        "skipped": "⏭️",
    }
    
    status_colors = {
        "pending": "dim",
        "running": "yellow",
        "completed": "green",
        "failed": "red",
        "skipped": "blue",
    }
    
    icon = status_icons.get(status, "❓")
    color = status_colors.get(status, "white")
    
    return Panel(
        f"[{color}]{icon} {step_name}[/{color}]",
        box=box.ROUNDED,
        border_style=color,
        padding=(0, 2),
    )

def create_success_panel(result: Dict[str, Any]) -> Panel:
    """Create the final success panel."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", justify="right")
    table.add_column(style="green")
    
    table.add_row("🎬 Video:", f"[green]{result.get('video_path', 'N/A')}[/green]")
    table.add_row("⏱️  Duration:", f"{result.get('duration', 0):.1f}s")
    table.add_row("📊 File Size:", result.get('file_size', 'N/A'))
    
    panel = Panel(
        table,
        title="[bold green]🎉 SUCCESS! Video Generated[/bold green]",
        box=box.DOUBLE_EDGE,
        border_style="green",
        padding=(1, 2),
    )
    return panel

def create_error_panel(error_message: str, suggestion: str) -> Panel:
    """Create an error panel with helpful suggestion."""
    panel = Panel(
        f"[bold red]{error_message}[/bold red]\n\n[yellow]💡 {suggestion}[/yellow]",
        title="[bold red]❌ ERROR[/bold red]",
        box=box.ROUNDED,
        border_style="red",
        padding=(1, 2),
    )
    return panel

# =============================================================================
# STEP 1: TOPIC RESEARCH & SCRIPT GENERATION
# =============================================================================

class ScriptGenerator:
    """Generate engaging narration scripts for history shorts."""
    
    # Engaging hooks for different topics
    HOOKS = [
        "Did you know that {topic} changed the course of history forever?",
        "The untold story of {topic} will shock you.",
        "What really happened during {topic}? The truth is stranger than fiction.",
        "{topic}: The event that shaped our modern world.",
        "Before {topic}, the world was never the same. Here's why.",
        "The incredible true story behind {topic}.",
        "{topic} - A tale of courage, betrayal, and destiny.",
    ]
    
    # Transition phrases
    TRANSITIONS = [
        "But here's where it gets interesting...",
        "What happened next changed everything...",
        "The twist? It gets even more dramatic...",
        "And then, the unthinkable occurred...",
        "But wait, there's more to this story...",
    ]
    
    # Closing phrases
    CLOSINGS = [
        "History remembers {topic} as a turning point that echoes to this day.",
        "The legacy of {topic} continues to shape our world.",
        "{topic} - proof that truth is often stranger than fiction.",
        "Remember {topic}, because those who forget history are doomed to repeat it.",
        "The story of {topic} reminds us that history is made by the bold.",
    ]
    
    def __init__(self):
        wikipedia.set_lang("en")
    
    @retry_decorator()
    def fetch_wikipedia_info(self, topic: str) -> Tuple[str, str, List[str]]:
        """Fetch information from Wikipedia about the topic."""
        try:
            # Search for the topic
            search_results = wikipedia.search(topic, results=3)
            if not search_results:
                raise PageError(f"No Wikipedia results for: {topic}")
            
            # Get the first (most relevant) page
            page = wikipedia.page(search_results[0], auto_suggest=False)
            
            # Extract summary (first 2-3 paragraphs)
            summary = wikipedia.summary(search_results[0], sentences=5, auto_suggest=False)
            
            # Extract interesting facts (from sections if available)
            facts = []
            try:
                # Try to get sections
                sections = page.sections if hasattr(page, 'sections') else []
                for section in sections[:3]:  # First 3 sections
                    facts.append(section[:200])
            except Exception:
                pass
            
            # If no facts from sections, create from summary
            if not facts:
                sentences = summary.split('. ')
                facts = [s.strip() + '.' for s in sentences[:5] if len(s) > 20]
            
            return page.title, summary, facts
            
        except DisambiguationError as e:
            # Try the first option from disambiguation
            if e.options:
                return self.fetch_wikipedia_info(e.options[0])
            raise
        except PageError:
            # Return generic info if page not found
            return topic, f"{topic} is a fascinating historical subject with rich details waiting to be explored.", []
    
    def generate_script(self, topic: str, duration: float = 55.0) -> ScriptData:
        """Generate a narration script using Grok AI, with Wikipedia context."""
        logger.info(f"📚 Researching topic: [cyan]{topic}[/cyan]")

        title, summary, facts = self.fetch_wikipedia_info(topic)

        # Target word count — edge-tts Christopher Neural reads ~155 wpm
        words_per_minute = 155
        target_words = int((duration / 60) * words_per_minute)

        narration = self._generate_narration_with_grok(title, summary, target_words)

        word_count = len(narration.split())
        estimated_duration = (word_count / words_per_minute) * 60
        tags = self._generate_tags(topic, title)

        script = ScriptData(
            topic=topic,
            title=title,
            narration=narration,
            facts=facts,
            wikipedia_summary=summary,
            tags=tags,
            estimated_duration=max(MIN_DURATION, min(MAX_DURATION, estimated_duration)),
        )

        logger.info(f"✅ Script generated: [green]{word_count} words[/green], ~[green]{estimated_duration:.0f}s[/green]")
        logger.debug(f"Script preview: {narration[:200]}...")

        return script

    def _generate_narration_with_grok(self, title: str, summary: str, target_words: int) -> str:
        """Call Grok text API to write the narration. Falls back to Wikipedia stitching on error."""
        api_key = config.get("xai_api_key", "")
        if not api_key:
            logger.warning("⚠️  No XAI_API_KEY — falling back to Wikipedia-based script")
            return self._fallback_narration(title, summary, target_words)

        system_msg = (
            "You are a master historian and viral YouTube Shorts scriptwriter. "
            "You combine the narrative precision of a BBC documentary with the hook-driven "
            "pacing of the most-watched history channels (Oversimplified, Kings and Generals, "
            "History Hit). Every fact you write is historically verified and specific — "
            "no vague claims, no approximations, no filler."
        )

        prompt = (
            f'Write EXACTLY {target_words} words of spoken narration for a 60-second YouTube Short about "{title}".\n\n'
            f"Wikipedia source material (extract the most historically significant, specific facts):\n"
            f"{summary[:2000]}\n\n"
            f"Script requirements:\n"
            f"- EXACTLY {target_words} words — count word by word before responding\n"
            f"- Hook: Open with ONE shocking, historically specific fact or statistic "
            f"(a real number, date, casualty count, or direct quote) — something that stops the scroll instantly\n"
            f"- Body: 3-4 incredible verified facts with real numbers, real names, real dates — "
            f"prioritize facts most people don't know\n"
            f"- Historical accuracy: every claim must be directly supported by the Wikipedia source above\n"
            f"- Pacing: short punchy sentences for impact, vary rhythm like a great documentary narrator\n"
            f"- Tone: dramatic but factual — no fluff, no filler, no 'it's interesting that'\n"
            f"- Ending: one powerful sentence giving the viewer a lasting takeaway or modern context\n"
            f"- NO stage directions, NO headings, NO bullet points — pure spoken narration only\n\n"
            f"Output ONLY the narration text. Nothing else."
        )

        try:
            response = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config["grok_script_model"],
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 500,
                    "temperature": 0.7,
                },
                timeout=30,
            )
            response.raise_for_status()
            narration = response.json()["choices"][0]["message"]["content"].strip()
            logger.debug(f"Grok script model: {config['grok_script_model']}, words: {len(narration.split())}")
            return narration
        except Exception as e:
            logger.warning(f"⚠️  Grok script API failed: {e} — falling back to Wikipedia-based script")
            return self._fallback_narration(title, summary, target_words)

    def _fallback_narration(self, title: str, summary: str, target_words: int) -> str:
        """Simple fallback: stitch Wikipedia sentences to fill target word count."""
        hook = random.choice(self.HOOKS).format(topic=title)
        closing = random.choice(self.CLOSINGS).format(topic=title)
        sentences = [s.strip() for s in summary.replace("\n", " ").split(". ") if len(s.strip()) > 30]
        budget = target_words - len(hook.split()) - len(closing.split())
        body_parts = []
        for s in sentences:
            if budget <= 0:
                break
            body_parts.append(s)
            budget -= len(s.split())
        body = ". ".join(body_parts)
        if body and not body.endswith("."):
            body += "."
        return f"{hook} {body} {closing}".strip()
    
    def _generate_tags(self, topic: str, title: str) -> List[str]:
        """Generate relevant tags for the video."""
        base_tags = ["history", "shorts", "educational", "facts", "documentary"]
        
        # Add topic-specific tags
        topic_words = topic.lower().split()
        topic_tags = [w for w in topic_words if len(w) > 3]
        
        # Add title-based tags
        title_words = title.lower().split()
        title_tags = [w.strip('.,!?;:') for w in title_words if len(w) > 3]
        
        all_tags = list(dict.fromkeys(base_tags + topic_tags + title_tags))  # Remove duplicates, preserve order
        return all_tags[:15]  # Limit to 15 tags

# =============================================================================
# STEP 2: VIDEO GENERATION
# =============================================================================

class VideoGenerator:
    """Generate video content using Grok Imagine or MoviePy fallback."""

    def __init__(self, use_grok: bool = False, local_only: bool = False):
        self.use_grok = use_grok and not local_only
        self.local_only = local_only
        self.xai_client = None

        if self.use_grok and XAI_AVAILABLE and config["xai_api_key"]:
            try:
                self.xai_client = XAIClient(api_key=config["xai_api_key"])
                logger.success("✅ Grok Imagine Video API ready")
            except Exception as e:
                logger.warning(f"⚠️  Grok init failed: {e} → falling back to MoviePy")
                self.use_grok = False
        else:
            self.use_grok = False

    @retry_decorator()
    def generate_video(self, script: ScriptData, duration: float) -> VideoAssets:
        """Main entry point — Grok Imagine only."""
        return self._generate_with_grok(script, duration)

    def _generate_with_grok(self, script: ScriptData, duration: float) -> VideoAssets:
        """Grok Imagine Video — with native voiceover + music."""
        logger.info("🎬 Generating cinematic video with Grok Imagine (native audio)...")

        GROK_MAX = 12  # safe max per clip in March 2026
        segments = max(1, int(duration / GROK_MAX) + 1)

        intro_prompt = f"""
        Ultra-cinematic vertical 9:16 historical documentary, opening title sequence.
        Historical subject: {script.title}

        Visual direction:
        - Dramatic wide establishing shot of the historical setting, battlefield, or location
        - Historically accurate to the era: correct uniforms, weapons, architecture, and lighting
        - Single cinematic title card: "{script.title}" with the key historical date, gold serif font
        - Atmosphere: dawn light or stormy overcast sky, dust and smoke drifting through the air
        - Camera movement: slow dolly-in or crane shot, deeply cinematic and immersive

        Style: BBC/Netflix prestige historical documentary — real reenactment aesthetic, NOT animation
        Color: desaturated with warm golden highlights, filmic grain, high contrast shadows
        Format: vertical 9:16, 720p. Only one title card — no other text on screen.
        """

        # Distinct scene types that cycle across action clips for visual variety
        action_scenes = [
            f"intense battlefield action — soldiers charging, cavalry, artillery firing — "
            f"historically accurate uniforms and weapons of the era of {script.title}",
            f"dramatic close-ups of key historical leaders and figures from {script.title} — "
            f"period-accurate costume, torchlit or daylight, intense determined expressions",
            f"the human aftermath — exhausted soldiers, fallen warriors, civilians, "
            f"the landscape in the wake of {script.title}",
            f"historical detail shots — period maps, weapons, flags, artifacts, "
            f"documents, and symbolic objects from the era of {script.title}",
        ]

        video_clips = []
        for i in range(segments):
            logger.info(f"   Generating clip {i+1}/{segments}...")
            if i == 0:
                prompt = intro_prompt
            else:
                scene = action_scenes[(i - 1) % len(action_scenes)]
                prompt = f"""
        Ultra-cinematic vertical 9:16 historical documentary continuation.
        Historical subject: {script.title}
        Scene focus: {scene}

        CRITICAL: NO text overlays, NO title cards, NO subtitles, NO on-screen words of any kind.
        Pure cinematic footage only — historically accurate to the period.

        Style: BBC/Netflix prestige historical documentary reenactment — NOT animation, NOT CGI cartoon
        Camera: slow motion on peak action moments, intimate close-ups on faces and weapons,
                wide shots for scale and atmosphere
        Color: period-appropriate grading, filmic grain, dramatic chiaroscuro lighting
        Format: vertical 9:16, 720p
        """

            # Retry each clip up to 3 times before giving up on Grok entirely
            clip = None
            for attempt in range(3):
                try:
                    response = self.xai_client.video.generate(
                        prompt=prompt,
                        model="grok-imagine-video",
                        duration=min(GROK_MAX, duration),
                        aspect_ratio="9:16",
                        resolution=config["video_resolution"]
                    )
                    with temp_file(suffix=".mp4") as tmp:
                        r = requests.get(response.url, stream=True, timeout=60)
                        r.raise_for_status()
                        with open(tmp, "wb") as f:
                            for chunk in r.iter_content(8192):
                                f.write(chunk)
                        clip = VideoFileClip(str(tmp)).without_audio()
                    break  # success
                except Exception as e:
                    if attempt < 2:
                        logger.warning(f"   Clip {i+1} attempt {attempt+1} failed: {e} — retrying...")
                        time.sleep(3)
                    else:
                        raise  # let outer handler fall back to MoviePy

            video_clips.append(clip)

        # Concatenate
        from moviepy.video.compositing.concatenate import concatenate_videoclips
        final_clip = concatenate_videoclips(video_clips) if len(video_clips) > 1 else video_clips[0]
        final_clip = final_clip.subclip(0, min(duration, final_clip.duration))

        # Save
        output_path = OUTPUT_DIR / f"grok_{script.topic.replace(' ', '_')[:30]}_{int(time.time())}.mp4"
        final_clip.write_videofile(str(output_path), fps=config["video_fps"], codec="libx264", audio=False, logger=None)

        for c in video_clips:
            c.close()
        final_clip.close()

        logger.success(f"✅ Grok Imagine video ready ({duration:.1f}s, video-only — edge-tts audio added in assembly)")
        return VideoAssets(video_path=output_path, duration=duration)
    
    def _create_grok_prompt(self, script: ScriptData) -> str:
        """Create an optimized prompt for Grok Imagine."""
        topic = script.title
        facts_preview = " ".join(script.facts[:2]) if script.facts else script.wikipedia_summary[:200]
        
        prompt = f"""
        Cinematic historical documentary style, vertical 9:16 format.
        Topic: {topic}
        
        Visual elements:
        - Dramatic historical imagery and reenactments
        - Ancient maps, artifacts, and battle scenes
        - Moody atmospheric lighting with golden hour tones
        - Slow cinematic camera movements
        - Professional documentary aesthetic
        
        Content context: {facts_preview}
        
        Style: Epic historical documentary, National Geographic style, 
        cinematic color grading, 4K quality, vertical format for mobile.
        """
        
        return prompt.strip()
    
    def _generate_with_moviepy(self, script: ScriptData, duration: float) -> VideoAssets:
        """Generate video using MoviePy - creates engaging slideshow with facts."""
        logger.info("🎬 Generating cinematic video with MoviePy...")
        
        # Create a slideshow of fact cards and title cards
        clips = []
        current_time = 0
        
        # 1. Opening title card (5 seconds)
        title_duration = min(5.0, duration)
        title_card = self._create_title_card_with_pil(script.title, duration=title_duration)
        if title_card:
            title_card = title_card.set_start(0).set_position('center')
            clips.append(title_card)
            current_time = title_duration
        
        # 2. Create fact cards from script content
        facts = self._extract_facts_for_slideshow(script)
        remaining_duration = duration - current_time
        card_duration = max(4.0, remaining_duration / len(facts)) if facts and remaining_duration > 0 else 5.0
        
        for i, fact in enumerate(facts):
            remaining_time = duration - current_time
            if remaining_time <= 0:
                break
            
            fact_duration = min(card_duration, remaining_time)
            fact_card = self._create_fact_card_with_pil(
                fact=fact,
                topic=script.title,
                index=i + 1,
                total=len(facts),
                duration=fact_duration
            )
            if fact_card:
                fact_card = fact_card.set_start(current_time).set_position('center')
                clips.append(fact_card)
                current_time += fact_duration
        
        # 3. Add closing card if there's remaining time
        if current_time < duration:
            remaining = duration - current_time
            if remaining > 0:
                closing_card = self._create_closing_card_with_pil(script.title, duration=remaining)
                if closing_card:
                    closing_card = closing_card.set_start(current_time).set_position('center')
                    clips.append(closing_card)
        
        # Create a solid background (NOT transparent)
        bg_color = (20, 25, 45)  # Dark blue-gray
        background = ColorClip(
            size=(SHORTS_WIDTH, SHORTS_HEIGHT),
            color=bg_color,
        ).set_duration(duration)
        
        # Composite all clips over background
        final_clip = CompositeVideoClip([background] + clips, size=(SHORTS_WIDTH, SHORTS_HEIGHT))
        final_clip = final_clip.set_duration(duration)
        
        # Save video
        output_path = OUTPUT_DIR / f"history_short_{script.topic.replace(' ', '_')[:30]}_{int(time.time())}.mp4"
        
        with temp_file(suffix=".mp4") as temp_path:
            final_clip.write_videofile(
                str(temp_path),
                fps=config["video_fps"],
                codec="libx264",
                audio=False,
                preset="medium",
                threads=4,
                logger=None,
            )
            shutil.copy2(temp_path, output_path)
        
        final_clip.close()
        background.close()
        for clip in clips:
            clip.close()
        
        assets = VideoAssets(
            video_path=output_path,
            duration=duration,
        )
        
        logger.info(f"✅ MoviePy video generated: [green]{output_path}[/green]")
        return assets
    
    def _extract_facts_for_slideshow(self, script: ScriptData) -> List[str]:
        """Extract key facts from script for slideshow."""
        facts = []
        
        # Add facts from script
        if script.facts:
            facts.extend(script.facts[:5])
        
        # If not enough facts, split the summary into sentences
        if len(facts) < 3:
            sentences = re.split(r'[.!?]+', script.wikipedia_summary)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) > 30 and len(facts) < 6:
                    facts.append(sentence + '.')
        
        # Ensure we have at least 3 cards
        if len(facts) < 3:
            facts.append(f"Learn more about {script.title}")
            facts.append("A fascinating historical journey")
            facts.append("History comes alive")
        
        return facts[:6]  # Maximum 6 fact cards
    
    def _create_animated_background(self, duration: float) -> VideoFileClip:
        """Create an animated gradient background."""
        # Use PIL to create animated frames
        import numpy as np
        
        def make_frame(t):
            """Generate animated gradient frame."""
            img = Image.new('RGB', (SHORTS_WIDTH, SHORTS_HEIGHT))
            draw = ImageDraw.Draw(img)
            
            # Color cycling based on time
            t_cycle = (t % 20) / 20  # 20 second cycle
            
            # Dark historical theme colors
            colors = [
                [(20, 25, 45), (35, 30, 55)],    # Dark blue to purple
                [(25, 20, 40), (45, 30, 50)],    # Purple to deep purple
                [(30, 25, 35), (50, 35, 45)],    # Burgundy tones
                [(20, 30, 40), (35, 50, 55)],    # Teal tones
            ]
            
            color_pair = colors[int(t_cycle * len(colors)) % len(colors)]
            color1, color2 = color_pair
            
            # Draw vertical gradient
            for y in range(SHORTS_HEIGHT):
                ratio = y / SHORTS_HEIGHT
                r = int(color1[0] + (color2[0] - color1[0]) * ratio)
                g = int(color1[1] + (color2[1] - color1[1]) * ratio)
                b = int(color1[2] + (color2[2] - color1[2]) * ratio)
                draw.line([(0, y), (SHORTS_WIDTH, y)], fill=(r, g, b))
            
            return np.array(img)
        
        # Create VideoClip from frames
        from moviepy.video.io.bindings import mplfig_to_npimage
        
        # For simplicity, use a ColorClip with slow color change
        base_color = (25, 25, 45)
        background = ColorClip(
            size=(SHORTS_WIDTH, SHORTS_HEIGHT),
            color=base_color,
        ).set_duration(duration)

        return background

    def _create_fact_card_with_pil(self, fact: str, topic: str, index: int, total: int, duration: float = 5.0) -> Optional[ImageClip]:
        """Create a fact card using PIL."""
        try:
            # Create image with decorative background
            img = Image.new('RGB', (SHORTS_WIDTH, SHORTS_HEIGHT), color=(20, 25, 45))
            draw = ImageDraw.Draw(img)
            
            # Try system fonts
            font_paths = [
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
            ]
            
            title_font = None
            body_font = None
            for font_path in font_paths:
                try:
                    title_font = ImageFont.truetype(font_path, 48)
                    body_font = ImageFont.truetype(font_path, 42)
                    break
                except Exception:
                    continue
            
            if title_font is None:
                title_font = ImageFont.load_default()
            if body_font is None:
                body_font = ImageFont.load_default()
            
            # Draw decorative border
            border_color = (255, 215, 0)  # Gold
            margin = 30
            draw.rectangle(
                [margin, margin, SHORTS_WIDTH - margin, SHORTS_HEIGHT - margin],
                outline=border_color,
                width=4
            )
            
            # Draw fact number
            fact_label = f"FACT {index}/{total}"
            label_bbox = draw.textbbox((0, 0), fact_label, font=title_font)
            label_width = label_bbox[2] - label_bbox[0]
            draw.text(((SHORTS_WIDTH - label_width) // 2, 60), fact_label, font=title_font, fill=(255, 215, 0))
            
            # Draw separator line
            draw.line([(margin + 50, 120), (SHORTS_WIDTH - margin - 50, 120)], fill=(255, 215, 0), width=2)
            
            # Draw fact text (word wrap)
            words = fact.split()
            lines = []
            current_line = []
            max_line_width = SHORTS_WIDTH - (margin * 4)
            
            for word in words:
                current_line.append(word)
                test_text = ' '.join(current_line)
                test_bbox = draw.textbbox((0, 0), test_text, font=body_font)
                if test_bbox[2] - test_bbox[0] > max_line_width:
                    current_line.pop()
                    if current_line:
                        lines.append(' '.join(current_line))
                    current_line = [word]
            if current_line:
                lines.append(' '.join(current_line))
            
            # Center and draw lines
            total_text_height = len(lines) * 50
            start_y = (SHORTS_HEIGHT - total_text_height) // 2 + 50
            
            for i, line in enumerate(lines):
                line_bbox = draw.textbbox((0, 0), line, font=body_font)
                line_width = line_bbox[2] - line_bbox[0]
                x = (SHORTS_WIDTH - line_width) // 2
                y = start_y + (i * 50)
                # Shadow
                draw.text((x + 2, y + 2), line, font=body_font, fill=(0, 0, 0))
                # Main text
                draw.text((x, y), line, font=body_font, fill=(255, 255, 255))
            
            # Draw topic at bottom
            topic_bbox = draw.textbbox((0, 0), topic, font=title_font)
            topic_width = topic_bbox[2] - topic_bbox[0]
            draw.text(((SHORTS_WIDTH - topic_width) // 2, SHORTS_HEIGHT - 100), topic, font=title_font, fill=(255, 215, 0))
            
            import numpy as np
            img_array = np.array(img)
            return ImageClip(img_array).set_duration(duration)
            
        except Exception as e:
            logger.warning(f"⚠️  Fact card creation failed: {e}")
            return ColorClip(size=(SHORTS_WIDTH, SHORTS_HEIGHT), color=(30, 30, 50)).set_duration(duration)
    
    def _create_closing_card_with_pil(self, topic: str, duration: float = 5.0) -> Optional[ImageClip]:
        """Create a closing card using PIL."""
        try:
            img = Image.new('RGB', (SHORTS_WIDTH, SHORTS_HEIGHT), color=(15, 23, 42))
            draw = ImageDraw.Draw(img)
            
            font_paths = ["/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Arial.ttf"]
            font = None
            for font_path in font_paths:
                try:
                    font = ImageFont.truetype(font_path, 64)
                    break
                except Exception:
                    continue
            
            if font is None:
                font = ImageFont.load_default()
            
            # Draw decorative elements
            center_y = SHORTS_HEIGHT // 2
            
            # Draw circle/ornament
            draw.ellipse(
                [SHORTS_WIDTH // 2 - 100, center_y - 100, SHORTS_WIDTH // 2 + 100, center_y + 100],
                outline=(255, 215, 0),
                width=3
            )
            
            # Draw text
            text1 = "THANKS FOR WATCHING"
            text2 = f"Learn more about {topic}"
            
            bbox1 = draw.textbbox((0, 0), text1, font=font)
            w1 = bbox1[2] - bbox1[0]
            draw.text(((SHORTS_WIDTH - w1) // 2, center_y - 150), text1, font=font, fill=(255, 255, 255))
            
            smaller_font = font
            try:
                smaller_font = ImageFont.truetype(font_paths[0], 42) if font_paths else font
            except Exception:
                pass
            
            bbox2 = draw.textbbox((0, 0), text2, font=smaller_font)
            w2 = bbox2[2] - bbox2[0]
            draw.text(((SHORTS_WIDTH - w2) // 2, center_y + 150), text2, font=smaller_font, fill=(255, 215, 0))
            
            import numpy as np
            img_array = np.array(img)
            return ImageClip(img_array).set_duration(duration)
            
        except Exception as e:
            logger.warning(f"⚠️  Closing card creation failed: {e}")
            return ColorClip(size=(SHORTS_WIDTH, SHORTS_HEIGHT), color=(20, 25, 45)).set_duration(duration)

    def _create_title_card_with_pil(self, title: str, duration: float = 5.0) -> Optional[ImageClip]:
        """Create a title card using PIL (no ImageMagick dependency)."""
        try:
            import numpy as np
            
            # Create image with PIL - SOLID BACKGROUND
            img = Image.new('RGB', (SHORTS_WIDTH, SHORTS_HEIGHT), color=(15, 23, 42))
            draw = ImageDraw.Draw(img)
            
            # Try to use system fonts
            font_paths = [
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Helvetica.ttc",
                "/Library/Fonts/Arial.ttf",
                "/Library/Fonts/Arial Bold.ttf",
            ]
            
            font = None
            for font_path in font_paths:
                try:
                    font = ImageFont.truetype(font_path, 80)
                    break
                except Exception:
                    continue
            
            # Fallback to default
            if font is None:
                try:
                    font = ImageFont.load_default()
                except Exception:
                    font = None
            
            # Draw title text
            title_text = title.upper()
            
            # Calculate text bounding box for centering
            if font:
                bbox = draw.textbbox((0, 0), title_text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                text_width = len(title_text) * 60  # Estimate
                text_height = 100
            
            x = (SHORTS_WIDTH - text_width) // 2
            y = (SHORTS_HEIGHT - text_height) // 2
            
            # Draw text with shadow effect
            if font:
                # Shadow (black, offset)
                draw.text((x + 4, y + 4), title_text, font=font, fill=(0, 0, 0))
                # Main text (white)
                draw.text((x, y), title_text, font=font, fill=(255, 255, 255))
            else:
                # No font - draw a simple rectangle with text indication
                draw.rectangle([x - 20, y - 20, x + text_width + 20, y + text_height + 20], 
                             fill=(50, 50, 50), outline=(255, 255, 255), width=5)
            
            # Add subtitle text "HISTORY SHORTS"
            subtitle = "HISTORY SHORTS"
            sub_font_size = 40
            try:
                for fp in font_paths:
                    try:
                        sub_font = ImageFont.truetype(fp, sub_font_size)
                        break
                    except Exception:
                        sub_font = None
                if sub_font is None:
                    sub_font = font
            except Exception:
                sub_font = font
            
            if sub_font:
                sub_bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
                sub_width = sub_bbox[2] - sub_bbox[0]
                sub_x = (SHORTS_WIDTH - sub_width) // 2
                draw.text((sub_x, y + text_height + 40), subtitle, font=sub_font, fill=(255, 215, 0))  # Gold
            
            # Convert to numpy array for MoviePy
            img_array = np.array(img)
            
            # Create ImageClip
            clip = ImageClip(img_array).set_duration(duration)
            return clip
            
        except Exception as e:
            logger.warning(f"⚠️  Title card creation failed: {e}")
            # Return a simple color clip as fallback with visible color
            return ColorClip(
                size=(SHORTS_WIDTH, SHORTS_HEIGHT),
                color=(50, 50, 80),  # Visible blue-gray
            ).set_duration(duration)

# =============================================================================
# STEP 3: TEXT-TO-SPEECH
# =============================================================================

class TTSGenerator:
    """Generate speech audio using edge-tts."""
    
    # Alternative TTS options (commented for reference)
    # For Kokoro-82M (local TTS):
    #   from kokoro import KModel
    #   model = KModel()
    #   audio = model.generate(text, voice="af_bella")
    #
    # For Coqui TTS:
    #   from TTS.api import TTS
    #   tts = TTS("tts_models/en/ljspeech/tacotron2-DDC")
    #   tts.tts_to_file(text=text, file_path=output_path)
    #
    # For pyttsx3 (offline):
    #   import pyttsx3
    #   engine = pyttsx3.init()
    #   engine.save_to_file(text, output_path)
    #   engine.runAndWait()
    
    def __init__(self):
        self.voice = config["tts_voice"]
        self.rate = config["tts_rate"]
        self.volume = config["tts_volume"]
    
    @retry_decorator()
    async def generate_audio(self, script: ScriptData) -> VideoAssets:
        """Generate TTS audio for the narration."""
        logger.info(f"🎤 Generating TTS audio with voice: [cyan]{self.voice}[/cyan]")
        
        # Clean narration for TTS (remove special characters that might cause issues)
        clean_narration = self._clean_text_for_tts(script.narration)
        
        output_path = OUTPUT_DIR / f"audio_{script.topic.replace(' ', '_')[:30]}_{int(time.time())}.mp3"
        
        # Initialize edge-tts
        communicate = edge_tts.Communicate(
            clean_narration,
            self.voice,
            rate=self.rate,
            volume=self.volume,
        )
        
        # Generate audio
        await communicate.save(str(output_path))
        
        # Get duration
        duration = self._get_audio_duration(output_path)
        
        assets = VideoAssets(
            audio_path=output_path,
            duration=duration,
        )
        
        logger.info(f"✅ TTS audio generated: [green]{duration:.1f}s[/green]")
        return assets
    
    def _clean_text_for_tts(self, text: str) -> str:
        """Clean text for TTS processing."""
        # Remove problematic characters
        text = re.sub(r'[^\w\s.,!?;:\'\"-]', '', text)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove excessive punctuation
        text = re.sub(r'([.,!?;:])\1+', r'\1', text)
        return text.strip()
    
    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get audio duration using moviepy."""
        try:
            audio = AudioFileClip(str(audio_path))
            duration = audio.duration
            audio.close()
            return duration
        except Exception:
            # Fallback: estimate from file size and bitrate
            # Average MP3 bitrate ~128kbps
            file_size = audio_path.stat().st_size
            estimated_duration = (file_size * 8) / (128 * 1000)
            return max(MIN_DURATION, min(MAX_DURATION, estimated_duration))

# =============================================================================
# STEP 4: SUBTITLE GENERATION
# =============================================================================

class SubtitleGenerator:
    """Generate animated karaoke-style subtitles using PIL (no ImageMagick)."""

    def __init__(self):
        self.font_size = config["subtitle_font_size"]
        self.font_color = config["subtitle_color"]
        self.outline_color = config["subtitle_outline_color"]
        self.outline_width = SUBTITLE_OUTLINE_WIDTH

    def generate_subtitles(self, script: ScriptData, audio_duration: float) -> VideoAssets:
        """Generate SRT subtitle file."""
        logger.info("📝 Generating subtitles...")

        # Split narration into subtitle segments
        segments = self._split_into_segments(script.narration, audio_duration)

        # Write SRT file
        output_path = OUTPUT_DIR / f"subtitles_{script.topic.replace(' ', '_')[:30]}_{int(time.time())}.srt"

        with open(output_path, "w", encoding="utf-8") as f:
            current_time = 0.0
            for i, (text, duration) in enumerate(segments, 1):
                start = self._seconds_to_srt_time(current_time)
                end = self._seconds_to_srt_time(current_time + duration)
                f.write(f"{i}\n{start} --> {end}\n{text}\n\n")
                current_time += duration

        assets = VideoAssets(
            subtitle_path=output_path,
            duration=audio_duration,
        )

        logger.info(f"✅ Subtitles generated: [green]{len(segments)} segments[/green]")
        return assets

    def _seconds_to_srt_time(self, seconds: float) -> str:
        """Convert seconds to SRT timestamp format HH:MM:SS,mmm."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _split_into_segments(self, text: str, total_duration: float) -> List[Tuple[str, float]]:
        """Split text into timed subtitle segments."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return []

        total_words = sum(len(s.split()) for s in sentences)
        words_per_second = total_words / total_duration if total_duration > 0 else 2.5

        segments = []
        for sentence in sentences:
            word_count = len(sentence.split())
            duration = word_count / words_per_second if words_per_second > 0 else 2
            duration = max(1.5, min(4, duration))
            segments.append((sentence, duration))

        return segments

    def _create_subtitle_clip_with_pil(self, text: str, duration: float, start_time: float) -> ImageClip:
        """Create a subtitle clip using PIL (no ImageMagick dependency)."""
        try:
            # Create transparent background
            img = Image.new('RGBA', (SHORTS_WIDTH, SHORTS_HEIGHT), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Try system fonts
            font_paths = [
                "/System/Library/Fonts/Helvetica.ttc",
                "/System/Library/Fonts/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
            ]
            
            font = None
            for font_path in font_paths:
                try:
                    font = ImageFont.truetype(font_path, self.font_size)
                    break
                except Exception:
                    continue
            
            # Calculate text position
            if font:
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                text_width = len(text) * 30
                text_height = self.font_size
            
            x = (SHORTS_WIDTH - text_width) // 2
            y = SHORTS_HEIGHT - 200 - text_height // 2
            
            # Draw text with outline effect (draw multiple times with offset)
            outline_color = (0, 0, 0, 255)  # Black
            text_color = (255, 255, 0, 255)  # Yellow
            
            if font:
                # Draw outline (shadow effect)
                for dx in [-2, -1, 0, 1, 2]:
                    for dy in [-2, -1, 0, 1, 2]:
                        if dx != 0 or dy != 0:
                            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
                # Draw main text
                draw.text((x, y), text, font=font, fill=text_color)
            else:
                # Fallback: simple rectangle
                draw.rectangle([x - 10, y - 10, x + text_width + 10, y + text_height + 10],
                             fill=(0, 0, 0, 200), outline=(255, 255, 0, 255), width=2)
            
            # Convert to numpy array
            import numpy as np
            img_array = np.array(img)
            
            # Create ImageClip with transparency
            clip = ImageClip(img_array, transparent=True).set_duration(duration).set_start(start_time).set_position(('center', SHORTS_HEIGHT - 200))
            return clip
            
        except Exception as e:
            logger.warning(f"⚠️  Subtitle clip failed: {e}")
            # Fallback: black bar
            return ColorClip(
                size=(SHORTS_WIDTH, 100),
                color=(0, 0, 0),
            ).set_duration(duration).set_start(start_time).set_position(('center', SHORTS_HEIGHT - 200))
    
    def _create_empty_subtitle_track(self, duration: float) -> Path:
        """Create an empty subtitle track."""
        output_path = OUTPUT_DIR / f"subtitles_empty_{int(time.time())}.mp4"
        
        blank = ColorClip(
            size=(SHORTS_WIDTH, SHORTS_HEIGHT),
            color=(0, 0, 0),
        ).set_duration(duration)

        with temp_file(suffix=".mp4") as temp_path:
            blank.write_videofile(
                str(temp_path),  # Convert Path to string for MoviePy 1.x
                fps=config["video_fps"],
                codec="libx264",
                audio=False,
                logger=None,
            )
            shutil.copy2(temp_path, output_path)

        blank.close()
        return output_path

# =============================================================================
# STEP 5: VIDEO ASSEMBLY
# =============================================================================

class VideoAssembler:
    """Assemble final video from components."""

    def assemble(self, video_assets: VideoAssets, audio_assets: VideoAssets,
                 subtitle_assets: VideoAssets, script: ScriptData) -> VideoAssets:
        """Combine all assets into final video.

        Strategy: MoviePy composites video + subtitle overlays (handles transparency
        in memory correctly), writes video-only to a temp file, then ffmpeg muxes
        the MP3 audio in (reliable audio stream mapping).
        """
        logger.info("🎬 Assembling final video...")

        timestamp = int(time.time())
        safe_topic = re.sub(r'[^\w\s-]', '', script.topic)[:30].strip()
        output_filename = f"history_short_{safe_topic}_{timestamp}.mp4"
        output_path = OUTPUT_DIR / output_filename

        try:
            video_path = video_assets.video_path
            audio_path = audio_assets.audio_path
            srt_path = subtitle_assets.subtitle_path if subtitle_assets else None

            if not video_path or not video_path.exists():
                raise FileNotFoundError(f"Video not found: {video_path}")
            if not audio_path or not audio_path.exists():
                raise FileNotFoundError(f"Audio not found: {audio_path}")

            # Get audio duration
            audio_clip = AudioFileClip(str(audio_path))
            final_duration = audio_clip.duration
            audio_clip.close()

            # Loop video to fill full TTS audio duration, scale to target resolution
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",        # loop Grok video indefinitely
                "-i", str(video_path),
                "-i", str(audio_path),
                "-vf", f"scale={SHORTS_WIDTH}:{SHORTS_HEIGHT}",
                "-map", "0:v",
                "-map", "1:a",
                "-c:v", "libx264",
                "-c:a", "aac",
                "-preset", "medium",
                "-shortest",                 # stop when audio (narrator) ends
                str(output_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")

            final_duration = audio_assets.duration
            file_size = self._format_file_size(output_path.stat().st_size)

            assets = VideoAssets(
                video_path=output_path,
                audio_path=audio_path,
                subtitle_path=srt_path,
                duration=final_duration,
            )

            logger.info(f"✅ Final video assembled: [green]{output_path}[/green] ({file_size})")
            return assets

        except Exception as e:
            logger.error(f"❌ Assembly failed: {e}")
            raise

    def _create_clips_from_srt(self, srt_path: Path) -> list:
        """Parse SRT file and return transparent PIL ImageClips for each subtitle."""
        import re as _re
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont

        font = None
        for font_path in [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ]:
            try:
                font = ImageFont.truetype(font_path, config["subtitle_font_size"])
                break
            except Exception:
                continue

        srt_text = srt_path.read_text(encoding="utf-8")
        # Parse blocks: index, timestamps, text
        blocks = _re.split(r'\n\n+', srt_text.strip())
        clips = []

        def _srt_time_to_seconds(ts: str) -> float:
            h, m, rest = ts.split(":")
            s, ms = rest.split(",")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        for block in blocks:
            lines = block.strip().splitlines()
            if len(lines) < 3:
                continue
            # lines[0] = index, lines[1] = timestamp, lines[2:] = text
            try:
                start_str, end_str = lines[1].split(" --> ")
                start = _srt_time_to_seconds(start_str.strip())
                end = _srt_time_to_seconds(end_str.strip())
                text = " ".join(lines[2:])
            except Exception:
                continue

            duration = end - start
            if duration <= 0:
                continue

            # Render RGBA image with transparent background
            img = Image.new("RGBA", (SHORTS_WIDTH, SHORTS_HEIGHT), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            if font:
                bbox = draw.textbbox((0, 0), text, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            else:
                tw = len(text) * 28
                th = config["subtitle_font_size"]

            x = (SHORTS_WIDTH - tw) // 2
            y = SHORTS_HEIGHT - 200 - th // 2

            # Outline
            for dx in [-2, -1, 0, 1, 2]:
                for dy in [-2, -1, 0, 1, 2]:
                    if dx != 0 or dy != 0:
                        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 255))
            draw.text((x, y), text, font=font, fill=(255, 255, 0, 255))

            img_array = np.array(img)
            clip = (
                ImageClip(img_array, transparent=True)
                .set_start(start)
                .set_duration(duration)
            )
            clips.append(clip)

        return clips
    
    def _format_file_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

# =============================================================================
# MAIN PIPELINE
# =============================================================================

class HistoryShortsPipeline:
    """Main pipeline orchestrating all steps."""
    
    def __init__(self, use_grok: bool = False, local_only: bool = False,
                 verbose: bool = False):
        self.use_grok = use_grok
        self.local_only = local_only
        self.verbose = verbose

        # Initialize components
        self.script_generator = ScriptGenerator()
        self.video_generator = VideoGenerator(use_grok=use_grok, local_only=local_only)
        self.tts_generator = TTSGenerator()
        self.subtitle_generator = SubtitleGenerator()
        self.video_assembler = VideoAssembler()
    
    def run(self, topic: str) -> Dict[str, Any]:
        """Execute the full pipeline with live Rich progress bars."""
        result = {
            "success": False,
            "topic": topic,
            "video_path": None,
            "duration": 0,
            "file_size": None,
            "error": None,
        }

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                console=console,
            ) as progress:

                # Step 1: Generate script
                t1 = progress.add_task("📖 Researching & writing script...", total=100)
                script = self.script_generator.generate_script(topic, config["video_duration"])
                progress.update(t1, completed=100)
                console.print(f"  [green]✓[/green] Topic: {script.title} (~{script.estimated_duration:.0f}s)")

                # Step 2: Generate video
                t2 = progress.add_task("🎥 Generating video (Grok Imagine or MoviePy)...", total=100)
                video_assets = self.video_generator.generate_video(script, script.estimated_duration)
                progress.update(t2, completed=100)
                console.print(f"  [green]✓[/green] Video: {video_assets.video_path.name if video_assets.video_path else 'N/A'}")

                # Step 3: Generate TTS
                t3 = progress.add_task("🗣️  Generating voiceover (edge-tts)...", total=100)
                audio_assets = asyncio.run(self.tts_generator.generate_audio(script))
                progress.update(t3, completed=100)
                console.print(f"  [green]✓[/green] Audio: {audio_assets.audio_path.name if audio_assets.audio_path else 'N/A'}")

                # Step 4: Generate subtitles
                t4 = progress.add_task("✍️  Burning animated subtitles...", total=100)
                subtitle_assets = self.subtitle_generator.generate_subtitles(script, audio_assets.duration)
                progress.update(t4, completed=100)
                console.print(f"  [green]✓[/green] Subtitles: {subtitle_assets.subtitle_path.name if subtitle_assets.subtitle_path else 'N/A'}")

                # Step 5: Assemble final video
                t5 = progress.add_task("🎞️  Assembling final Short...", total=100)
                final_assets = self.video_assembler.assemble(
                    video_assets, audio_assets, subtitle_assets, script
                )
                progress.update(t5, completed=100)
                result["video_path"] = str(final_assets.video_path)
                result["duration"] = final_assets.duration
                result["file_size"] = self.video_assembler._format_file_size(
                    final_assets.video_path.stat().st_size
                )
                console.print(f"  [green]✓[/green] Final: {final_assets.video_path.name}")

            result["success"] = True
            return result

        except Exception as e:
            logger.exception(f"Pipeline failed: {e}")
            result["error"] = str(e)
            return result

# =============================================================================
# CLI COMMANDS
# =============================================================================

app = typer.Typer(
    name="history-shorts",
    help="🏛️ History Shorts Factory - Automatic YouTube Shorts Generator",
    add_completion=False,
)

@app.command("run")
def run(
    topic: Optional[str] = typer.Option(
        None,
        "--topic", "-t",
        help="History topic to generate content about (e.g., 'World War II', 'Ancient Rome')",
    ),
    daily: bool = typer.Option(
        False,
        "--daily",
        help="Run in daily mode (generates one video per hour)",
    ),
    use_grok_imagine: bool = typer.Option(
        False,
        "--use-grok-imagine",
        help="Use Grok Imagine Video API for video generation",
    ),
    local_only: bool = typer.Option(
        False,
        "--local-only",
        help="Use only local processing (no external APIs)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Enable verbose/debug logging",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet", "-q",
        help="Suppress non-essential output",
    ),
) -> None:
    """
    Generate a history YouTube Short.

    Examples:
        python history_shorts.py run --topic "World War II" --use-grok-imagine
        python history_shorts.py run --daily --use-grok-imagine
        python history_shorts.py run -t "Battle of Waterloo" -v
    """
    # Setup logging
    setup_logging(verbose=verbose, quiet=quiet)
    
    # Show startup panel
    if not quiet:
        console.print(create_startup_panel())
        console.print()
    
    # Determine topic
    actual_topic = topic or config["default_topic"]
    
    if daily:
        _run_daily_mode(
            topic=actual_topic,
            use_grok_imagine=use_grok_imagine,
            local_only=local_only,
            verbose=verbose,
            quiet=quiet,
        )
    else:
        _run_single(
            topic=actual_topic,
            use_grok_imagine=use_grok_imagine,
            local_only=local_only,
            verbose=verbose,
            quiet=quiet,
        )

def _run_single(
    topic: str,
    use_grok_imagine: bool,
    local_only: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    """Run a single video generation."""
    try:
        # Create pipeline
        pipeline = HistoryShortsPipeline(
            use_grok=use_grok_imagine,
            local_only=local_only,
            verbose=verbose,
        )
        
        # Run pipeline
        result = pipeline.run(topic)
        
        # Show result
        if result["success"]:
            if not quiet:
                console.print()
                console.print(create_success_panel(result))
            logger.info(f"🎉 Video generation complete: {result['video_path']}")
        else:
            error_msg = result.get('error', 'Unknown error')
            suggestion = "Check the logs for details and try again with --verbose"
            if "api" in error_msg.lower():
                suggestion = "Check your API keys and network connection"
            
            if not quiet:
                console.print()
                console.print(create_error_panel(error_msg, suggestion))
            logger.error(f"❌ Video generation failed: {error_msg}")
            sys.exit(1)
            
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
        cleanup_temp_files()
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        if not quiet:
            console.print(create_error_panel(str(e), "Run with --verbose for detailed logs"))
        sys.exit(1)
    finally:
        cleanup_temp_files()

def _run_daily_mode(
    topic: str,
    use_grok_imagine: bool,
    local_only: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    """Run in daily mode (continuous generation)."""
    console.print("\n[bold green]🔄 Daily Mode Activated[/bold green]")
    console.print("[dim]Generating one video every hour. Press Ctrl+C to stop.[/dim]\n")

    interval = 3600  # 1 hour

    iteration = 0
    while not shutdown_requested:
        iteration += 1
        start_time = datetime.now()

        console.print(f"\n[bold cyan]═══════ Generation #{iteration} ═══════[/bold cyan]")

        # Run single generation
        _run_single(
            topic=topic,
            use_grok_imagine=use_grok_imagine,
            local_only=local_only,
            verbose=verbose,
            quiet=quiet,
        )
        
        # Calculate next run time
        next_run = start_time.replace(second=0, microsecond=0)
        next_run = next_run.replace(minute=0)
        next_run = next_run.replace(hour=(next_run.hour + 1) % 24)
        
        # Countdown
        console.print(f"\n[yellow]⏰ Next generation in 1 hour...[/yellow]")
        
        # Sleep with progress
        sleep_interval = interval
        while sleep_interval > 0 and not shutdown_requested:
            time.sleep(min(60, sleep_interval))
            sleep_interval -= 60
            
            if not shutdown_requested:
                remaining = sleep_interval // 60
                console.print(f"[dim]  Next video in {remaining} minutes...[/dim]")

@app.command("info")
def show_info() -> None:
    """Show application information and configuration."""
    setup_logging(quiet=True)
    
    table = Table(title="History Shorts Factory - Configuration", box=box.ROUNDED)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="white")
    
    table.add_row("Version", APP_VERSION)
    table.add_row("Output Directory", str(OUTPUT_DIR))
    table.add_row("Logs Directory", str(LOGS_DIR))
    table.add_row("Default Topic", config["default_topic"])
    table.add_row("Video Duration", f"{config['video_duration']}s")
    table.add_row("TTS Voice", config["tts_voice"])
    table.add_row("Video Resolution", f"{SHORTS_WIDTH}x{SHORTS_HEIGHT}")
    table.add_row("Grok API Available", "✅" if (XAI_AVAILABLE and config["xai_api_key"]) else "❌")
    
    console.print(table)

@app.command("topics")
def suggest_topics(count: int = typer.Option(5, "--count", "-c")) -> None:
    """Suggest interesting history topics."""
    setup_logging(quiet=True)
    
    topics = [
        "The Fall of Rome",
        "Ancient Egypt",
        "World War II",
        "The Renaissance",
        "Viking Age",
        "The Crusades",
        "Alexander the Great",
        "The Industrial Revolution",
        "Samurai Japan",
        "The Cold War",
        "Medieval Knights",
        "The Ottoman Empire",
        "The French Revolution",
        "Ancient Greece",
        "The Mongol Empire",
        "The American Revolution",
        "The Aztec Empire",
        "The British Empire",
        "The Silk Road",
        "The Black Death",
    ]
    
    selected = random.sample(topics, min(count, len(topics)))
    
    table = Table(title="📚 Suggested History Topics", box=box.ROUNDED)
    table.add_column("#", style="dim")
    table.add_column("Topic", style="cyan")
    
    for i, topic in enumerate(selected, 1):
        table.add_row(str(i), topic)
    
    console.print(table)
    console.print(f"\n[dim]Use: python history_shorts.py run --topic \"Topic Name\"[/dim]")

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Goodbye![/yellow]")
        cleanup_temp_files()
        sys.exit(0)
    except Exception as e:
        error_console.print(f"[bold red]Fatal Error:[/bold red] {e}")
        logger.exception("Fatal error at entry point")
        cleanup_temp_files()
        sys.exit(1)
