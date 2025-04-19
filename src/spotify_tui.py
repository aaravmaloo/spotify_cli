import os
import asyncio
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Input, Label, Static
from textual.containers import Vertical, Horizontal
from textual.keys import Keys
from textual.binding import Binding

# Load credentials from secrets.env file
load_dotenv("secrets.env")
client_id = os.getenv("SPOTIFY_CLIENT_ID")
client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")

# Spotify authentication
scope = "user-library-read user-read-playback-state user-modify-playback-state"
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=client_id,
    client_secret=client_secret,
    redirect_uri="http://127.0.0.1:8888/callback",
    scope=scope
))

class SpotifyTUI(App):
    """Spotify TUI Application"""

    BINDINGS = [
        Binding("ctrl+f", "focus_search", "Search"),
        Binding("escape", "blur_search", "Back", show=False)
    ]

    CSS = """
    Screen {
        background: #0f0f1a;
        padding: 2 0 0 0;
        align: center middle;
    }
    Header {
        background: #0f0f1a;
        color: #b266ff;
        text-style: bold;
        align: center top;
    }
    #main-vertical {
        align: center middle;
        width: 50;
    }
    Input {
        border: none;
        background: #1a1a28;
        color: #e0e0e0;
        width: 100%;
        margin-bottom: 1;
        padding: 0 1;
    }
    #results {
        background: #0f0f1a;
        color: #e0e0e0;
        width: 100%;
        height: 8;
        margin-bottom: 1;
        padding: 0 1;
        border: none;
    }
    #player-bar {
        width: 100%;
        height: 3;
        dock: bottom;
        background: #1a1a28;
        color: #e0e0e0;
        border-top: solid #b266ff;
        align: center middle;
        padding: 0 1;
    }
    #controls {
        width: auto;
        height: 3;
        color: #b266ff;
        align: center middle;
    }
    #now-playing {
        width: auto;
        height: 3;
        color: #e0e0e0;
        margin-left: 2;
    }
    Footer {
        background: #0f0f1a;
        color: #b266ff;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-vertical"):
            yield Label("Search for a track:", id="search-label")
            yield Input(placeholder="Enter track name...", id="search-input")
            yield Static("Type to search...", id="results")
        with Horizontal(id="player-bar"):
            yield Label("Controls: Space=Play/Pause | N=Next | P=Previous | Ctrl+F=Search", id="controls")
            yield Label("Not Playing", id="now-playing")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Spotify TUI"
        self.query = ""
        self.track_uri = None
        self.selected_index = 0
        self.results = []
        self.search_task = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        # Get initial playback state
        try:
            playback = sp.current_playback()
            self.is_playing = playback and playback.get('is_playing', False)
            if playback and playback.get('item'):
                self.query_one("#now-playing").update(f"Playing: {playback['item']['name']}")
        except:
            self.is_playing = False

    def search_spotify(self, query: str):
        """Execute Spotify search in a separate thread"""
        if not query.strip():
            return []
        try:
            results = sp.search(q=query, type="track", limit=5)
            return results["tracks"]["items"]
        except Exception:
            return []

    async def delayed_search(self, query: str):
        """Debounced search with delay"""
        await asyncio.sleep(0.2)  # Reduced to 200ms for better responsiveness
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            self.executor, 
            partial(self.search_spotify, query)
        )
        self.results = results
        results_box = self.query_one("#results", Static)
        if results:
            self.selected_index = 0  # Reset selection on new results
            results_box.update("\n".join(
                f"{'>' if i == self.selected_index else ' '} {item['name']} by {item['artists'][0]['name']}"
                for i, item in enumerate(results)
            ))
        else:
            results_box.update("No results" if query else "Type to search...")

    async def on_input_changed(self, event: Input.Changed) -> None:
        self.query = event.value.strip()
        
        # Cancel any pending search
        if self.search_task and not self.search_task.done():
            self.search_task.cancel()
        
        # Clear results if query is empty
        if not self.query:
            self.results = []
            self.query_one("#results", Static).update("Type to search...")
            return

        # Start new real-time search
        self.search_task = asyncio.create_task(self.delayed_search(self.query))

    async def handle_playback(self, action: str) -> None:
        """Handle playback controls in background"""
        status = self.query_one("#now-playing", Label)

        try:
            # Get current state first
            playback = sp.current_playback()
            current_state = playback and playback.get('is_playing', False)
            
            if action == "play_pause":
                if current_state:
                    sp.pause_playback()
                    self.is_playing = False
                    status.update("Paused")
                else:
                    sp.start_playback()
                    self.is_playing = True
                    if playback and playback.get('item'):
                        status.update(f"Playing: {playback['item']['name']}")
            elif action in ["next", "previous"]:
                getattr(sp, f"{action}_track")()
                self.is_playing = True
                await asyncio.sleep(0.1)
                new_playback = sp.current_playback()
                if new_playback and new_playback.get('item'):
                    status.update(f"Playing: {new_playback['item']['name']}")

        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 404:  # No active device
                status.update("Error: No active Spotify device found")
            else:
                status.update(f"Playback Error: {str(e)}")

    async def update_track_name(self, status: Label) -> None:
        """Update track name in background"""
        try:
            await asyncio.sleep(0.1)  # Minimum delay to let Spotify update
            playback = await asyncio.get_event_loop().run_in_executor(
                self.executor, sp.current_playback
            )
            if playback and playback['item']:
                status.update(f"Playing: {playback['item']['name']}")
        except:
            pass  # Ignore errors in background update

    async def action_focus_search(self) -> None:
        """Focus the search input."""
        self.query_one("#search-input").focus()

    async def action_blur_search(self) -> None:
        """Blur the search input."""
        self.query_one("#search-input").blur()

    async def on_key(self, event: Keys) -> None:
        input_widget = self.query_one("#search-input", Input)
        results_box = self.query_one("#results", Static)
        status = self.query_one("#now-playing", Label)

        # Handle playback controls only when search is not focused
        if not input_widget.has_focus:
            if event.key == "space":
                asyncio.create_task(self.handle_playback("play_pause"))
            elif event.key == "n":
                asyncio.create_task(self.handle_playback("next"))
            elif event.key == "p":
                asyncio.create_task(self.handle_playback("previous"))
            return

        # Search results navigation
        if input_widget.has_focus and self.results:
            if event.key == "down":
                self.selected_index = min(self.selected_index + 1, len(self.results) - 1)
                results_box.update("\n".join(
                    f"{'>' if i == self.selected_index else ' '} {item['name']} by {item['artists'][0]['name']}"
                    for i, item in enumerate(self.results)
                ))
            elif event.key == "up":
                self.selected_index = max(self.selected_index - 1, 0)
                results_box.update("\n".join(
                    f"{'>' if i == self.selected_index else ' '} {item['name']} by {item['artists'][0]['name']}"
                    for i, item in enumerate(self.results)
                ))
            elif event.key == "enter":
                self.track_uri = self.results[self.selected_index]["uri"]
                try:
                    sp.start_playback(uris=[self.track_uri])
                    track_name = self.results[self.selected_index]['name']
                    status.update(f"Playing: {track_name}")
                except spotipy.SpotifyException:
                    status.update("Playback Error")
            return

    async def on_unmount(self) -> None:
        """Cleanup resources"""
        self.executor.shutdown(wait=False)

if __name__ == "__main__":
    app = SpotifyTUI()
    app.run()