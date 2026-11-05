import os
import sys
import glob
import shutil
import subprocess
import threading
import queue
import re
import base64
import json
import httpx
import io
import ctypes
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urljoin, urlparse
from bs4 import BeautifulSoup
import customtkinter as ctk
from tkinter import messagebox, filedialog
from PIL import Image, ImageOps
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

# Fix Taskbar Icon for Windows
try:
    myappid = 'mytoon.downloader.pro.v1'
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

# Appearance - Premium Dark Theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

APP_DATA_DIR = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "MYTOON-Downloader")
SETTINGS_PATH = os.path.join(APP_DATA_DIR, "settings.json")
DEFAULT_SETTINGS = {
    "save_path": os.path.join(os.path.expanduser("~"), "Downloads", "MYTOON"),
    "save_as": "images",
    "workers": "4",
    "skip_existing": True,
    "delete_after_convert": False,
}


class DownloadCancelled(Exception):
    """Raised inside worker threads when the user presses the cancel button."""


def resource_path(relative_path):
    """Return absolute path to a bundled resource (works for PyInstaller .exe and plain script)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


def sanitize_filename(name, fallback="Webtoon"):
    """Make a string safe to use as a Windows folder name."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(name or "")).strip()
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > 80:
        name = name[:80].rstrip(" .")
    return name or fallback


def find_executable(name):
    """Locate a CLI tool (webtoon-downloader, gallery-dl) without hard-coded user paths."""
    found = shutil.which(name)
    if found:
        return found
    patterns = [
        os.path.expandvars(rf"%APPDATA%\Python\Python*\Scripts\{name}.exe"),
        os.path.expandvars(rf"%LOCALAPPDATA%\Programs\Python\Python*\Scripts\{name}.exe"),
        os.path.join(os.path.dirname(sys.executable), "Scripts", f"{name}.exe"),
    ]
    for pattern in patterns:
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return None

class WebtoonDownloaderGUI(ctk.CTk):
    def __init__(self):
        # Thread-safe UI queue: worker threads must never touch Tk directly
        self._ui_queue = queue.Queue()
        super().__init__()
        super().after(30, self._drain_ui_queue)

        self.title("MYTOON Pro — Studio Edition")
        self.geometry("1220x840")
        self.minsize(1040, 720)
        self.configure(fg_color="#06070A")

        # Studio Dark Design Tokens
        self.UCHIHA_RED = "#E61919"
        self.UCHIHA_DARK_RED = "#A81212"
        self.UCHIHA_BLACK = "#0B0D13"
        self.UCHIHA_GRAY = "#12151E"
        self.SURFACE_ELEVATED = "#171B26"
        self.BORDER_SUBTLE = "#222736"
        self.UCHIHA_TEXT = "#F1F5F9"
        self.TEXT_MUTED = "#94A3B8"
        self.ACCENT_GREEN = "#10B981"
        self.ACCENT_AMBER = "#F59E0B"
        self.ACCENT_BLUE = "#3B82F6"

        # Downloader Paths (auto-detected; no hard-coded user folders)
        self.downloader_path = find_executable("webtoon-downloader")
        self.gallery_dl_path = find_executable("gallery-dl")
        self.direct_scraper_domains = (
            "mytoon.site",
            "manhwaread.com",
            "manhuaus.com",
            "mgeko.cc",
            "asurascans.com",
            "hentai20.io",
            "kingofshojo.com",
            "nebula.mn"
        )
        self.supported_sites_window = None
        self.cached_mytoon_data = None
        self.cached_manga_mn_data = None
        self.verified_series = None
        self.detected_min_chapter = 1
        self.detected_max_chapter = None
        os.makedirs(APP_DATA_DIR, exist_ok=True)
        self.mytoon_session_path = os.path.join(APP_DATA_DIR, "mytoon_session.json")
        self.nebula_session_path = os.path.join(APP_DATA_DIR, "nebula_session.json")
        self.manga_mn_session_path = os.path.join(APP_DATA_DIR, "manga_mn_session.json")
        self.settings = self.load_settings()

        # Download control state
        self.cancel_event = threading.Event()
        self.current_process = None
        self.last_output_dir = None
        self._progress_lock = threading.Lock()
        self._progress_chapter_idx = 0
        self._progress_total_chapters = 1
        self._bytes_downloaded = 0
        self._speed_started_at = time.time()
        self._last_ui_progress = 0.0

        # Root Grid Layout (Sidebar + Main Workspace)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ==================================================================
        # 1. LEFT SIDEBAR — Structured Cards
        # ==================================================================
        self.sidebar_container = ctk.CTkFrame(
            self, width=365, corner_radius=0, fg_color=self.UCHIHA_BLACK,
            border_width=1, border_color="#181C26"
        )
        self.sidebar_container.grid(row=0, column=0, sticky="nsew")
        self.sidebar_container.grid_propagate(False)
        self.sidebar_container.grid_columnconfigure(0, weight=1)
        self.sidebar_container.grid_rowconfigure(1, weight=1)

        # Brand Header (Fixed at top of sidebar)
        self.brand_frame = ctk.CTkFrame(self.sidebar_container, fg_color="transparent")
        self.brand_frame.grid(row=0, column=0, padx=18, pady=(16, 8), sticky="ew")
        self.brand_frame.grid_columnconfigure(1, weight=1)

        try:
            logo_path = resource_path("logo.png")
            if os.path.exists(logo_path):
                logo_img_data = Image.open(logo_path)
                ico_path = resource_path("logo.ico")
                if not os.path.exists(ico_path):
                    ico_path = os.path.join(APP_DATA_DIR, "logo.ico")
                    if not os.path.exists(ico_path):
                        logo_img_data.save(ico_path, format="ICO", sizes=[(32, 32), (64, 64)])
                self.after(200, lambda p=ico_path: self.iconbitmap(p) if os.path.exists(p) else None)
                logo_image = ctk.CTkImage(light_image=logo_img_data, dark_image=logo_img_data, size=(68, 42))
                self.logo_label = ctk.CTkLabel(self.brand_frame, image=logo_image, text="")
                self.logo_label.grid(row=0, column=0, rowspan=2, padx=(0, 12), sticky="w")
            else:
                self.logo_label = ctk.CTkLabel(
                    self.brand_frame, text="M", width=44, height=44, corner_radius=10,
                    fg_color=self.UCHIHA_RED, font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
                    text_color="white"
                )
                self.logo_label.grid(row=0, column=0, rowspan=2, padx=(0, 12), sticky="w")
        except Exception:
            self.logo_label = ctk.CTkLabel(
                self.brand_frame, text="MYTOON",
                font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
                text_color=self.UCHIHA_RED
            )
            self.logo_label.grid(row=0, column=0, rowspan=2, padx=(0, 12), sticky="w")

        self.brand_title = ctk.CTkLabel(
            self.brand_frame, text="MYTOON PRO", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=19, weight="bold"), text_color="white"
        )
        self.brand_title.grid(row=0, column=1, sticky="sw")

        self.brand_subtitle = ctk.CTkLabel(
            self.brand_frame, text="STUDIO DOWNLOADER v2.0", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"), text_color=self.UCHIHA_RED
        )
        self.brand_subtitle.grid(row=1, column=1, sticky="nw")

        # Scrollable Sidebar Content
        self.sidebar_frame = ctk.CTkScrollableFrame(
            self.sidebar_container, width=340, corner_radius=0, fg_color="transparent",
            scrollbar_button_color="#1E2330", scrollbar_button_hover_color="#2D3548"
        )
        self.sidebar_frame.grid(row=1, column=0, sticky="nsew", padx=2, pady=(0, 6))
        self.sidebar_frame.grid_columnconfigure(0, weight=1)

        # --- CARD 1: URL Input & Quick Paste ---
        self.url_card = ctk.CTkFrame(
            self.sidebar_frame, corner_radius=14, fg_color=self.UCHIHA_GRAY,
            border_width=1, border_color=self.BORDER_SUBTLE
        )
        self.url_card.grid(row=0, column=0, padx=12, pady=(6, 8), sticky="ew")
        self.url_card.grid_columnconfigure(0, weight=1)

        self.url_header_row = ctk.CTkFrame(self.url_card, fg_color="transparent")
        self.url_header_row.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="ew")
        self.url_header_row.grid_columnconfigure(0, weight=1)

        self.url_label = ctk.CTkLabel(
            self.url_header_row, text="ВЭБТҮҮН ХАЯГ (URL)", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.TEXT_MUTED
        )
        self.url_label.grid(row=0, column=0, sticky="w")

        self.paste_button = ctk.CTkButton(
            self.url_header_row, text="Хуулж шалгах", width=102, height=24, corner_radius=6,
            command=self.paste_url_and_verify, fg_color=self.SURFACE_ELEVATED, hover_color="#252B3B",
            border_width=1, border_color="#2E364A", font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#E2E8F0"
        )
        self.paste_button.grid(row=0, column=1, sticky="e")

        self.url_input_row = ctk.CTkFrame(self.url_card, fg_color="transparent")
        self.url_input_row.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="ew")
        self.url_input_row.grid_columnconfigure(0, weight=1)

        self.url_entry = ctk.CTkEntry(
            self.url_input_row, placeholder_text="https://mytoon.site/webtoon/...", height=38,
            fg_color="#090B10", border_color="#262C3D", corner_radius=9,
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color="white"
        )
        self.url_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self.verify_url())
        self.url_entry.bind("<Control-v>", lambda e: self.after(100, self.verify_url))

        self.verify_button = ctk.CTkButton(
            self.url_input_row, text="Шалгах", width=68, height=38, corner_radius=9,
            command=self.verify_url, fg_color=self.UCHIHA_RED, hover_color=self.UCHIHA_DARK_RED,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        )
        self.verify_button.grid(row=0, column=1, sticky="e")

        # --- CARD 2: Media Info Preview Card ---
        self.info_card = ctk.CTkFrame(
            self.sidebar_frame, corner_radius=14, fg_color=self.UCHIHA_GRAY,
            border_width=1, border_color=self.BORDER_SUBTLE
        )
        self.info_card.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        self.info_card.grid_columnconfigure(0, weight=1)

        self.site_badge_label = ctk.CTkLabel(
            self.info_card, text="● МЭДЭЭЛЭЛ ХҮЛЭЭГДЭЖ БАЙНА", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            text_color=self.TEXT_MUTED
        )
        self.site_badge_label.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="ew")

        self.preview_image_label = ctk.CTkLabel(
            self.info_card, text="Хаяг оруулаад 'Шалгах' дарна уу", width=280, height=136,
            fg_color="#080A0F", corner_radius=10,
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#475569"
        )
        self.preview_image_label.grid(row=1, column=0, padx=14, pady=4, sticky="ew")

        self.webtoon_name_label = ctk.CTkLabel(
            self.info_card, text="Мэдээлэл байхгүй", anchor="w", justify="left",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=self.UCHIHA_TEXT, wraplength=280
        )
        self.webtoon_name_label.grid(row=2, column=0, padx=14, pady=(6, 12), sticky="ew")

        # --- CARD 3: Download Settings ---
        self.settings_card = ctk.CTkFrame(
            self.sidebar_frame, corner_radius=14, fg_color=self.UCHIHA_GRAY,
            border_width=1, border_color=self.BORDER_SUBTLE
        )
        self.settings_card.grid(row=2, column=0, padx=12, pady=6, sticky="ew")
        self.settings_card.grid_columnconfigure(0, weight=1)

        self.settings_label = ctk.CTkLabel(
            self.settings_card, text="ТАТАЛТЫН ТОХИРГОО", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.TEXT_MUTED
        )
        self.settings_label.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="w")

        # Chapter Range Row (Start — End)
        self.range_label = ctk.CTkLabel(
            self.settings_card, text="Бүлгийн дугаар (Эхлэх — Дуусах):", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#CBD5E1"
        )
        self.range_label.grid(row=1, column=0, padx=14, pady=(2, 4), sticky="w")

        self.range_frame = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        self.range_frame.grid(row=2, column=0, padx=14, pady=(0, 6), sticky="ew")
        self.range_frame.grid_columnconfigure(0, weight=1)
        self.range_frame.grid_columnconfigure(2, weight=1)

        self.start_entry = ctk.CTkEntry(
            self.range_frame, placeholder_text="Эхлэх", height=36, corner_radius=8,
            fg_color="#090B10", border_color="#262C3D", justify="center",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold")
        )
        self.start_entry.insert(0, "1")
        self.start_entry.grid(row=0, column=0, sticky="ew")

        self.range_sep_label = ctk.CTkLabel(
            self.range_frame, text="—", width=24,
            font=ctk.CTkFont(size=14, weight="bold"), text_color=self.TEXT_MUTED
        )
        self.range_sep_label.grid(row=0, column=1, padx=4)

        self.end_entry = ctk.CTkEntry(
            self.range_frame, placeholder_text="Дуусах", height=36, corner_radius=8,
            fg_color="#090B10", border_color="#262C3D", justify="center",
            font=ctk.CTkFont(family="Consolas", size=13, weight="bold")
        )
        self.end_entry.grid(row=0, column=2, sticky="ew")

        # Quick Range Preset Pills
        self.preset_frame = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        self.preset_frame.grid(row=3, column=0, padx=14, pady=(0, 10), sticky="ew")
        for col_i in range(4):
            self.preset_frame.grid_columnconfigure(col_i, weight=1)

        presets = [
            ("Бүгд", "all"),
            ("1-р бүлэг", "first"),
            ("Сүүлийнх", "latest"),
            ("+10 бүлэг", "plus10"),
        ]
        for idx_p, (p_label, p_mode) in enumerate(presets):
            btn = ctk.CTkButton(
                self.preset_frame, text=p_label, height=25, corner_radius=6,
                fg_color=self.SURFACE_ELEVATED, hover_color="#252B3B",
                border_width=1, border_color="#262C3D",
                font=ctk.CTkFont(family="Segoe UI", size=11), text_color="#CBD5E1",
                command=lambda m=p_mode: self.apply_range_preset(m)
            )
            btn.grid(row=0, column=idx_p, padx=(0 if idx_p == 0 else 4, 0), sticky="ew")

        # Format Segmented Control
        self.format_title_label = ctk.CTkLabel(
            self.settings_card, text="Хадгалах формат:", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#CBD5E1"
        )
        self.format_title_label.grid(row=4, column=0, padx=14, pady=(2, 4), sticky="w")

        self.format_combo = ctk.CTkSegmentedButton(
            self.settings_card, values=["images", "pdf", "cbz", "zip"], height=34, corner_radius=8,
            fg_color="#090B10", selected_color=self.UCHIHA_RED,
            selected_hover_color=self.UCHIHA_DARK_RED, unselected_color="#090B10",
            unselected_hover_color=self.SURFACE_ELEVATED,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            command=lambda _v: self.save_settings()
        )
        self.format_combo.set(self.settings.get("save_as", "images"))
        self.format_combo.grid(row=5, column=0, padx=14, pady=(0, 10), sticky="ew")

        # Concurrent Workers Segmented Control
        self.workers_label = ctk.CTkLabel(
            self.settings_card, text="Зэрэг татах урсгал (Threads):", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#CBD5E1"
        )
        self.workers_label.grid(row=6, column=0, padx=14, pady=(0, 4), sticky="w")

        self.workers_combo = ctk.CTkSegmentedButton(
            self.settings_card, values=["2", "4", "8", "12", "16"], height=32, corner_radius=8,
            fg_color="#090B10", selected_color=self.SURFACE_ELEVATED,
            selected_hover_color="#2A3144", unselected_color="#090B10",
            unselected_hover_color="#141824",
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            command=lambda _v: self.save_settings()
        )
        self.workers_combo.set(str(self.settings.get("workers", "4")))
        self.workers_combo.grid(row=7, column=0, padx=14, pady=(0, 10), sticky="ew")

        # Save Path Row
        self.path_title_label = ctk.CTkLabel(
            self.settings_card, text="Хадгалах хавтас:", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#CBD5E1"
        )
        self.path_title_label.grid(row=8, column=0, padx=14, pady=(0, 4), sticky="w")

        self.path_frame = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        self.path_frame.grid(row=9, column=0, padx=14, pady=(0, 10), sticky="ew")
        self.path_frame.grid_columnconfigure(0, weight=1)

        self.path_entry = ctk.CTkEntry(
            self.path_frame, placeholder_text="Хадгалах хавтас...", height=36, corner_radius=8,
            fg_color="#090B10", border_color="#262C3D",
            font=ctk.CTkFont(family="Segoe UI", size=11)
        )
        self.path_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.path_entry.insert(0, self.settings.get("save_path") or DEFAULT_SETTINGS["save_path"])
        self.path_entry.bind("<FocusOut>", lambda e: self.save_settings())

        self.browse_button = ctk.CTkButton(
            self.path_frame, text="Сонгох", width=68, height=36, corner_radius=8,
            command=self.browse_folder, fg_color=self.SURFACE_ELEVATED,
            hover_color="#252B3B", border_width=1, border_color="#2E364A",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        )
        self.browse_button.grid(row=0, column=1, sticky="e")

        # Switches for Resume & Cleanup
        self.options_frame = ctk.CTkFrame(self.settings_card, fg_color="transparent")
        self.options_frame.grid(row=10, column=0, padx=14, pady=(2, 14), sticky="ew")
        self.options_frame.grid_columnconfigure(0, weight=1)

        self.skip_existing_var = ctk.BooleanVar(value=bool(self.settings.get("skip_existing", True)))
        self.skip_existing_check = ctk.CTkSwitch(
            self.options_frame, text="Татсан зургийг алгасах (Resume)",
            variable=self.skip_existing_var, command=self.save_settings,
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#E2E8F0",
            progress_color=self.UCHIHA_RED, button_color="#F8FAFC", button_hover_color="#CBD5E1"
        )
        self.skip_existing_check.grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.delete_after_var = ctk.BooleanVar(value=bool(self.settings.get("delete_after_convert", False)))
        self.delete_after_check = ctk.CTkSwitch(
            self.options_frame, text="PDF/CBZ үүсгэсний дараа зургийг устгах",
            variable=self.delete_after_var, command=self.save_settings,
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#E2E8F0",
            progress_color=self.UCHIHA_RED, button_color="#F8FAFC", button_hover_color="#CBD5E1"
        )
        self.delete_after_check.grid(row=1, column=0, sticky="w")

        # --- CARD 4: VIP Accounts & Sessions ---
        self.accounts_card = ctk.CTkFrame(
            self.sidebar_frame, corner_radius=14, fg_color=self.UCHIHA_GRAY,
            border_width=1, border_color=self.BORDER_SUBTLE
        )
        self.accounts_card.grid(row=3, column=0, padx=12, pady=(6, 12), sticky="ew")
        self.accounts_card.grid_columnconfigure(0, weight=1)

        self.accounts_label = ctk.CTkLabel(
            self.accounts_card, text="АККАУНТ & VIP НЭВТРЭЛТ", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.TEXT_MUTED
        )
        self.accounts_label.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="w")

        self.mytoon_login_button = ctk.CTkButton(
            self.accounts_card, text="MYTOON НЭВТРЭХ", height=36, corner_radius=8,
            command=self.start_mytoon_login, fg_color=self.SURFACE_ELEVATED, hover_color="#252B3B",
            border_width=1, border_color=self.UCHIHA_RED,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=self.UCHIHA_TEXT
        )
        self.mytoon_login_button.grid(row=1, column=0, padx=14, pady=4, sticky="ew")

        self.nebula_login_button = ctk.CTkButton(
            self.accounts_card, text="NEBULA НЭВТРЭХ", height=36, corner_radius=8,
            command=self.start_nebula_login, fg_color=self.SURFACE_ELEVATED, hover_color="#252B3B",
            border_width=1, border_color="#7C3AED",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=self.UCHIHA_TEXT
        )
        self.nebula_login_button.grid(row=2, column=0, padx=14, pady=4, sticky="ew")

        self.manga_mn_login_button = ctk.CTkButton(
            self.accounts_card, text="MANGA.MN НЭВТРЭХ", height=36, corner_radius=8,
            command=self.start_manga_mn_login, fg_color=self.SURFACE_ELEVATED, hover_color="#252B3B",
            border_width=1, border_color="#10B981",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color=self.UCHIHA_TEXT
        )
        self.manga_mn_login_button.grid(row=3, column=0, padx=14, pady=(4, 12), sticky="ew")

        # Keep reference for backward compatibility
        self.supported_sites_button = None

        # ==================================================================
        # 2. MAIN WORKSPACE — Command Center Dashboard
        # ==================================================================
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="#06070A")
        self.main_frame.grid(row=0, column=1, padx=22, pady=18, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(3, weight=1)

        # --- Top Header Card ---
        self.header_frame = ctk.CTkFrame(
            self.main_frame, corner_radius=16, fg_color=self.UCHIHA_BLACK,
            border_width=1, border_color=self.BORDER_SUBTLE
        )
        self.header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.header_frame.grid_columnconfigure(0, weight=1)

        self.header_left = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.header_left.grid(row=0, column=0, padx=20, pady=14, sticky="w")

        self.title_row = ctk.CTkFrame(self.header_left, fg_color="transparent")
        self.title_row.pack(anchor="w")

        self.status_title = ctk.CTkLabel(
            self.title_row, text="ХЯНАХ САМБАР",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"), text_color="white"
        )
        self.status_title.pack(side="left", padx=(0, 12))

        self.state_badge = ctk.CTkLabel(
            self.title_row, text="● БЭЛЭН", height=24, corner_radius=12,
            fg_color="#12261E", text_color="#34D399", padx=10,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        )
        self.state_badge.pack(side="left")

        self.header_subtitle = ctk.CTkLabel(
            self.header_left, text="Олон урсгалт өндөр хурдны вэбтүүн болон манга татагч систем",
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color=self.TEXT_MUTED
        )
        self.header_subtitle.pack(anchor="w", pady=(2, 0))

        self.header_actions = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.header_actions.grid(row=0, column=1, padx=20, pady=14, sticky="e")

        self.supported_sites_header_button = ctk.CTkButton(
            self.header_actions, text="Дэмждэг сайтууд", height=42, width=148,
            command=self.show_supported_sites,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            fg_color=self.SURFACE_ELEVATED, hover_color="#252B3B",
            border_width=1, border_color="#2E364A", corner_radius=10
        )
        self.supported_sites_header_button.pack(side="left", padx=(0, 10))

        self.cancel_button = ctk.CTkButton(
            self.header_actions, text="ЗОГСООХ", height=42, width=115,
            command=self.cancel_download, state="disabled",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#171A24", hover_color="#7F1D1D",
            border_width=1, border_color="#333A4D", corner_radius=10
        )
        self.cancel_button.pack(side="left", padx=(0, 10))

        self.download_button = ctk.CTkButton(
            self.header_actions, text="▶  ТАТАЖ ЭХЛЭХ", height=44, width=185,
            command=self.start_download,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color=self.UCHIHA_RED, hover_color=self.UCHIHA_DARK_RED, corner_radius=11
        )
        self.download_button.pack(side="left")

        # --- KPI Live Metrics Strip (4 Cards) ---
        self.metrics_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.metrics_frame.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for col_m in range(4):
            self.metrics_frame.grid_columnconfigure(col_m, weight=1, uniform="metric")

        def make_metric_card(col, title_text, initial_val, accent_color):
            card = ctk.CTkFrame(
                self.metrics_frame, corner_radius=14, fg_color=self.UCHIHA_BLACK,
                border_width=1, border_color=self.BORDER_SUBTLE
            )
            card.grid(row=0, column=col, padx=(0 if col == 0 else 8, 0), sticky="ew")
            lbl_title = ctk.CTkLabel(
                card, text=title_text, anchor="w",
                font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"), text_color=self.TEXT_MUTED
            )
            lbl_title.pack(anchor="w", padx=16, pady=(10, 2))
            lbl_val = ctk.CTkLabel(
                card, text=initial_val, anchor="w",
                font=ctk.CTkFont(family="Consolas", size=18, weight="bold"), text_color=accent_color
            )
            lbl_val.pack(anchor="w", padx=16, pady=(0, 10))
            return lbl_val

        self.metric_chapters_value = make_metric_card(0, "БҮЛГИЙН ЯВЦ", "0 / 0", "#F8FAFC")
        self.metric_images_value = make_metric_card(1, "ТАТСАН ЗУРАГ", "0 / 0", "#60A5FA")
        self.metric_size_value = make_metric_card(2, "НИЙТ ХЭМЖЭЭ", "0.0 MB", "#34D399")
        self.metric_speed_value = make_metric_card(3, "ТАТАХ ХУРД", "0.00 MB/s", "#FBBF24")

        # --- Progress Bar & Live Status Card ---
        self.analytics_frame = ctk.CTkFrame(
            self.main_frame, corner_radius=14, fg_color=self.UCHIHA_BLACK,
            border_width=1, border_color=self.BORDER_SUBTLE
        )
        self.analytics_frame.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.analytics_frame.grid_columnconfigure(0, weight=1)

        self.progress_top_row = ctk.CTkFrame(self.analytics_frame, fg_color="transparent")
        self.progress_top_row.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 6))
        self.progress_top_row.grid_columnconfigure(0, weight=1)

        self.stats_label = ctk.CTkLabel(
            self.progress_top_row, text="Татахад бэлэн — URL оруулаад 'ТАТАЖ ЭХЛЭХ' дарна уу", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"), text_color="#CBD5E1"
        )
        self.stats_label.grid(row=0, column=0, sticky="w")

        self.percent_label = ctk.CTkLabel(
            self.progress_top_row, text="0.0%",
            font=ctk.CTkFont(family="Consolas", size=18, weight="bold"), text_color=self.UCHIHA_RED
        )
        self.percent_label.grid(row=0, column=1, sticky="e")

        self.progress_bar = ctk.CTkProgressBar(
            self.analytics_frame, progress_color=self.UCHIHA_RED, fg_color="#181C26",
            height=12, corner_radius=6
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))
        self.progress_bar.set(0)

        # --- Terminal Console Card ---
        self.terminal_card = ctk.CTkFrame(
            self.main_frame, corner_radius=16, fg_color=self.UCHIHA_BLACK,
            border_width=1, border_color=self.BORDER_SUBTLE
        )
        self.terminal_card.grid(row=3, column=0, sticky="nsew")
        self.terminal_card.grid_columnconfigure(0, weight=1)
        self.terminal_card.grid_rowconfigure(1, weight=1)

        self.footer_frame = ctk.CTkFrame(self.terminal_card, fg_color="transparent")
        self.footer_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        self.footer_frame.grid_columnconfigure(0, weight=1)

        self.console_title = ctk.CTkLabel(
            self.footer_frame, text="●  АЖИЛЛАГААНЫ ЛОГ (LIVE CONSOLE)", anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"), text_color=self.TEXT_MUTED
        )
        self.console_title.grid(row=0, column=0, sticky="w")

        self.console_btn_row = ctk.CTkFrame(self.footer_frame, fg_color="transparent")
        self.console_btn_row.grid(row=0, column=1, sticky="e")

        self.open_folder_button = ctk.CTkButton(
            self.console_btn_row, text="📂 Хавтас нээх", width=118, height=28, corner_radius=7,
            command=self.open_output_folder, fg_color=self.SURFACE_ELEVATED,
            hover_color="#252B3B", border_width=1, border_color=self.UCHIHA_RED,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold")
        )
        self.open_folder_button.pack(side="left", padx=(0, 8))

        self.copy_log_button = ctk.CTkButton(
            self.console_btn_row, text="Лог хуулах", width=96, height=28, corner_radius=7,
            command=self.copy_logs, fg_color=self.SURFACE_ELEVATED,
            hover_color="#252B3B", border_width=1, border_color="#2E364A",
            font=ctk.CTkFont(family="Segoe UI", size=11)
        )
        self.copy_log_button.pack(side="left", padx=(0, 8))

        self.clear_button = ctk.CTkButton(
            self.console_btn_row, text="Цэвэрлэх", width=90, height=28, corner_radius=7,
            command=self.clear_logs, fg_color=self.SURFACE_ELEVATED,
            hover_color="#252B3B", border_width=1, border_color="#2E364A",
            font=ctk.CTkFont(family="Segoe UI", size=11)
        )
        self.clear_button.pack(side="left")

        self.log_text = ctk.CTkTextbox(
            self.terminal_card, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color="#050609", border_width=1, border_color="#141822",
            text_color="#CBD5E1", corner_radius=12
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        try:
            tb = self.log_text._textbox
            tb.tag_config("ts", foreground="#475569")
            tb.tag_config("ok", foreground="#34D399")
            tb.tag_config("warn", foreground="#FBBF24")
            tb.tag_config("err", foreground="#F87171")
            tb.tag_config("accent", foreground="#60A5FA")
            tb.tag_config("info", foreground="#CBD5E1")
        except Exception:
            pass
        self.log_text.insert("0.0", "─── MYTOON Pro Studio v2.0 ───\nСистем ажиллахад бэлэн боллоо. Вэбтүүн хаягаа оруулна уу.\n\n")
        self.log_text.configure(state="disabled")

        self.downloading = False
        self.refresh_session_badges()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------
    # Thread-safe UI dispatch
    # ------------------------------------------------------------------
    def after(self, ms, func=None, *args):
        """Route calls from worker threads through a queue processed on the Tk main thread."""
        ui_queue = self.__dict__.get("_ui_queue")
        if func is not None and ui_queue is not None and threading.current_thread() is not threading.main_thread():
            ui_queue.put((func, args))
            return None
        return super().after(ms, func, *args)

    def _drain_ui_queue(self):
        try:
            for _ in range(200):
                func, args = self._ui_queue.get_nowait()
                try:
                    func(*args)
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            super().after(30, self._drain_ui_queue)
        except Exception:
            pass  # window destroyed

    # ------------------------------------------------------------------
    # Settings / session badges / helpers
    # ------------------------------------------------------------------
    def load_settings(self):
        settings = dict(DEFAULT_SETTINGS)
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        except (OSError, ValueError, TypeError):
            pass
        return settings

    def save_settings(self):
        try:
            self.settings.update({
                "save_path": self.path_entry.get().strip() or DEFAULT_SETTINGS["save_path"],
                "save_as": self.format_combo.get(),
                "workers": self.workers_combo.get(),
                "skip_existing": bool(self.skip_existing_var.get()),
                "delete_after_convert": bool(self.delete_after_var.get()),
            })
            os.makedirs(APP_DATA_DIR, exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def on_close(self):
        self.save_settings()
        if self.downloading:
            self.cancel_event.set()
            self.terminate_current_process()
        self.destroy()

    def read_session_cookies(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            return cookies if isinstance(cookies, list) else []
        except (OSError, ValueError, TypeError):
            return []

    def unexpired(self, cookies):
        now = time.time()
        return [c for c in cookies if not (isinstance(c.get("expires"), (int, float)) and 0 < c["expires"] < now)]

    def refresh_session_badges(self):
        mytoon_ok = self.is_valid_mytoon_session(self.unexpired(self.read_session_cookies(self.mytoon_session_path)))
        nebula_ok = any(
            c.get("name", "").startswith("wordpress_logged_in_")
            for c in self.unexpired(self.read_session_cookies(self.nebula_session_path))
        )
        manga_ok = bool(self.unexpired(self.read_session_cookies(self.manga_mn_session_path)))

        def apply(button, ok, ok_text, idle_text, idle_border):
            if str(button.cget("state")) == "disabled":
                return
            button.configure(
                text=f"●  {ok_text}" if ok else f"○  {idle_text}",
                text_color="#34D399" if ok else self.UCHIHA_TEXT,
                fg_color="#0F241D" if ok else self.SURFACE_ELEVATED,
                border_color="#10B981" if ok else idle_border,
            )

        apply(self.mytoon_login_button, mytoon_ok, "MYTOON: НЭВТЭРСЭН", "MYTOON НЭВТРЭХ", self.UCHIHA_RED)
        apply(self.nebula_login_button, nebula_ok, "NEBULA: НЭВТЭРСЭН", "NEBULA НЭВТРЭХ", "#7C3AED")
        apply(self.manga_mn_login_button, manga_ok, "MANGA.MN: НЭВТЭРСЭН", "MANGA.MN НЭВТРЭХ", "#10B981")

    def paste_url_and_verify(self):
        try:
            clip = self.clipboard_get().strip()
        except Exception:
            clip = ""
        if not clip:
            self.log("Clipboard хоосон байна. Эхлээд URL хаягаа хуулна уу.")
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, clip)
        self.verify_url()

    def apply_range_preset(self, mode):
        min_ch = max(1, int(self.detected_min_chapter or 1))
        max_ch = self.detected_max_chapter
        try:
            cur_start = int(self.start_entry.get().strip() or min_ch)
        except ValueError:
            cur_start = min_ch

        if mode == "first":
            s, e = min_ch, min_ch
        elif mode == "latest":
            s = e = max_ch if max_ch else cur_start
        elif mode == "all":
            s = min_ch
            e = max_ch if max_ch else cur_start
        elif mode == "plus10":
            s = cur_start
            e = min(cur_start + 9, max_ch) if max_ch else cur_start + 9
        else:
            return

        self.start_entry.delete(0, "end")
        self.start_entry.insert(0, str(s))
        self.end_entry.delete(0, "end")
        self.end_entry.insert(0, str(e))

    def set_app_state(self, state):
        styles = {
            "ready": ("● БЭЛЭН", "#12261E", "#34D399"),
            "running": ("● ТАТАЖ БАЙНА", "#2A1215", "#F87171"),
            "done": ("● ДУУССАН", "#12261E", "#34D399"),
            "cancelled": ("● ЗОГСООСОН", "#292012", "#FBBF24"),
            "warn": ("● АНХААР", "#292012", "#FBBF24"),
        }
        text, bg, fg = styles.get(state, styles["ready"])
        self.state_badge.configure(text=text, fg_color=bg, text_color=fg)

    def copy_logs(self):
        try:
            content = self.log_text.get("0.0", "end").strip()
            self.clipboard_clear()
            self.clipboard_append(content)
            self.log("Лог clipboard-д хуулагдлаа.")
        except Exception:
            pass

    def open_output_folder(self):
        folder = self.last_output_dir or self.path_entry.get().strip() or DEFAULT_SETTINGS["save_path"]
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
        except Exception as err:
            messagebox.showerror("Хавтас нээх", str(err))

    def cancel_download(self):
        if not self.downloading:
            return
        self.cancel_event.set()
        self.terminate_current_process()
        self.cancel_button.configure(state="disabled", text="ЗОГСООЖ БАЙНА...")
        self.log("Зогсоох хүсэлт илгээлээ. Одоогийн зургуудыг дуусгаад зогсоно...")

    def terminate_current_process(self):
        proc = self.current_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def check_cancel(self):
        if self.cancel_event.is_set():
            raise DownloadCancelled()

    def series_dir(self, title):
        """Per-webtoon output folder so different series never overwrite each other's chapters."""
        folder = os.path.join(self.current_save_path, sanitize_filename(title))
        os.makedirs(folder, exist_ok=True)
        self.last_output_dir = folder
        return folder

    def clean_series_title(self, raw_title, url=""):
        title = (raw_title or "").strip()
        title = re.split(r"\s+[|–—-]\s+", title)[0].strip()
        title = re.sub(r"(?i)\s*[-–—:|]?\s*(chapter|ch\.?|episode|ep\.?|бүлэг)\s*\d+.*$", "", title).strip()
        if title:
            return title
        parts = [p for p in unquote(urlparse(url).path).split("/") if p]
        parts = [p for p in parts if not re.search(r"(?i)chapter|^ch\d|^\d+$|reader|^en$|manga|comics|series", p)]
        return parts[-1].replace("-", " ").title() if parts else urlparse(url).netloc

    def guess_series_title(self, url):
        """Best-effort title for generic sites, preferring what verify_url already found."""
        vs = self.verified_series
        if vs and urlparse(vs.get("url", "")).netloc == urlparse(url).netloc and vs.get("title"):
            return vs["title"]
        return self.clean_series_title("", url)

    def begin_progress(self, total_chapters):
        with self._progress_lock:
            self._progress_total_chapters = max(1, total_chapters)
            self._progress_chapter_idx = 0
            self._bytes_downloaded = 0
            self._speed_started_at = time.time()
        def _init_ui():
            self.update_progress(0)
            self.metric_chapters_value.configure(text=f"0 / {self._progress_total_chapters}")
            self.metric_images_value.configure(text="0 / 0")
            self.metric_size_value.configure(text="0.0 MB")
            self.metric_speed_value.configure(text="0.00 MB/s")
        self.after(0, _init_ui)

    def set_chapter_progress(self, idx, label=""):
        self._progress_chapter_idx = idx
        pct = idx / self._progress_total_chapters * 100
        def _upd():
            self.update_progress(pct)
            self.metric_chapters_value.configure(text=f"{idx + 1} / {self._progress_total_chapters}")
            if label:
                self.stats_label.configure(text=label)
        self.after(0, _upd)

    def report_image_progress(self, done, total, ch_label=""):
        frac = (self._progress_chapter_idx + (done / max(1, total))) / self._progress_total_chapters
        elapsed = max(0.001, time.time() - self._speed_started_at)
        speed = self._bytes_downloaded / elapsed / (1024 * 1024)
        mb = self._bytes_downloaded / (1024 * 1024)
        ch_cur = self._progress_chapter_idx + 1
        ch_tot = self._progress_total_chapters
        text = (f"Бүлэг {ch_cur}/{ch_tot} {ch_label}  ·  "
                f"Зураг {done}/{total}  ·  {mb:.1f} MB  ·  {speed:.2f} MB/s")
        def _upd():
            self.update_progress(frac * 100)
            self.stats_label.configure(text=text)
            self.metric_chapters_value.configure(text=f"{ch_cur} / {ch_tot}")
            self.metric_images_value.configure(text=f"{done} / {total}")
            self.metric_size_value.configure(text=f"{mb:.1f} MB")
            self.metric_speed_value.configure(text=f"{speed:.2f} MB/s")
        self.after(0, _upd)

    def log(self, message):
        self.log_text.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        lower = message.lower()
        if any(k in lower for k in ("амжилттай", "үүсгэгдлээ", "хадгалсан", "saved")):
            tag = "ok"
        elif any(k in lower for k in ("алдаа", "error", "чадсангүй", "blocked")):
            tag = "err"
        elif any(k in lower for k in ("анхаар", "түгжээтэй", "зогсоо", "шаардлагатай", "олдсонгүй")):
            tag = "warn"
        elif any(k in lower for k in ("эхлүүлж", "engine:", "горим:", "webtoons:")):
            tag = "accent"
        else:
            tag = "info"
        try:
            tb = self.log_text._textbox
            tb.insert("end", f"[{ts}] ", "ts")
            tb.insert("end", f"{message}\n", tag)
        except Exception:
            self.log_text.insert("end", f"[{ts}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        
        # Only parse "%"-style progress from external CLI output (gallery-dl / webtoon-downloader)
        if self.current_process is not None:
            match_pct = re.search(r"(\d+(?:\.\d+)?)%", message)
            if match_pct:
                self.update_progress(float(match_pct.group(1)))

    def update_progress(self, percent):
        percent = max(0.0, min(100.0, float(percent)))
        self.progress_bar.set(percent / 100)
        self.percent_label.configure(text=f"{percent:.1f}%")

    def clear_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("0.0", "end")
        self.log_text.configure(state="disabled")
        self.update_progress(0)
        self.stats_label.configure(text="Бэлэн")
        self.metric_chapters_value.configure(text="0 / 0")
        self.metric_images_value.configure(text="0 / 0")
        self.metric_size_value.configure(text="0.0 MB")
        self.metric_speed_value.configure(text="0.00 MB/s")
        self.set_app_state("ready")

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)
            self.save_settings()

    def load_mytoon_cookies(self):
        try:
            with open(self.mytoon_session_path, "r", encoding="utf-8") as session_file:
                cookies = json.load(session_file)
            return {
                cookie["name"]: cookie["value"]
                for cookie in cookies
                if cookie.get("name") and cookie.get("value")
            }
        except (OSError, ValueError, TypeError):
            return {}

    def load_nebula_cookies(self):
        try:
            with open(self.nebula_session_path, "r", encoding="utf-8") as session_file:
                cookies = json.load(session_file)
            return {
                cookie["name"]: cookie["value"]
                for cookie in cookies
                if cookie.get("name") and cookie.get("value")
            }
        except (OSError, ValueError, TypeError):
            return {}

    def load_manga_mn_cookies(self):
        try:
            with open(self.manga_mn_session_path, "r", encoding="utf-8") as session_file:
                cookies = json.load(session_file)
            return {
                cookie["name"]: cookie["value"]
                for cookie in cookies
                if cookie.get("name") and cookie.get("value")
            }
        except (OSError, ValueError, TypeError):
            return {}

    def cookies_for_url(self, url):
        host = urlparse(url).netloc.lower()
        if host == "mytoon.site" or host.endswith(".mytoon.site"):
            return self.load_mytoon_cookies()
        if host == "nebula.mn" or host.endswith(".nebula.mn"):
            return self.load_nebula_cookies()
        if host == "manga.mn" or host.endswith(".manga.mn"):
            return self.load_manga_mn_cookies()
        return {}

    def launch_any_browser(self, playwright, headless=False):
        for ch in ["msedge", "chrome"]:
            try:
                return playwright.chromium.launch(channel=ch, headless=headless)
            except Exception:
                pass

        browser_paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for p in browser_paths:
            if os.path.exists(p):
                try:
                    return playwright.chromium.launch(executable_path=p, headless=headless)
                except Exception:
                    pass

        return playwright.chromium.launch(headless=headless)

    def launch_persistent_browser(self, playwright, profile_dir, headless=False):
        for ch in ["msedge", "chrome"]:
            try:
                return playwright.chromium.launch_persistent_context(
                    profile_dir,
                    channel=ch,
                    headless=headless,
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception:
                pass
        return playwright.chromium.launch_persistent_context(
            profile_dir,
            headless=headless,
        )

    def is_valid_mytoon_session(self, cookies):
        if not cookies:
            return False
        for c in cookies:
            name = c.get("name", "").lower()
            if name.startswith("sb-") and "auth-token" in name and not name.endswith("-code-verifier"):
                val = c.get("value", "")
                if len(val) > 20:
                    return True
        return False

    def start_mytoon_login(self):
        if sync_playwright is None:
            messagebox.showerror("Playwright алга", "Playwright суулгаагүй тул MyToon login browser нээж чадсангүй.")
            return
        self.mytoon_login_button.configure(state="disabled", text="BROWSER НЭЭЖ БАЙНА...")
        threading.Thread(target=self.run_mytoon_login, daemon=True).start()

    def run_mytoon_login(self):
        context = None
        try:
            profile_dir = os.path.join(os.path.dirname(self.mytoon_session_path), "mytoon_browser_profile")
            os.makedirs(profile_dir, exist_ok=True)
            self.after(0, self.log, "MyToon login browser нээгдлээ. Аккаунтаараа нэвтэрнэ үү.")
            with sync_playwright() as playwright:
                context = self.launch_persistent_browser(playwright, profile_dir, headless=False)
                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://mytoon.site", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1000)

                # Try opening login modal if not logged in
                try:
                    login_btn = page.locator("button:has-text('НЭВТРЭХ')").first
                    if login_btn.is_visible(timeout=2000):
                        login_btn.click()
                except Exception:
                    pass

                deadline = time.time() + 300
                saved = False
                last_cookies = []
                while time.time() < deadline:
                    if page.is_closed():
                        break
                    try:
                        last_cookies = context.cookies("https://mytoon.site")
                        if self.is_valid_mytoon_session(last_cookies):
                            page.wait_for_timeout(1500)
                            last_cookies = context.cookies("https://mytoon.site")
                            with open(self.mytoon_session_path, "w", encoding="utf-8") as session_file:
                                json.dump(last_cookies, session_file, ensure_ascii=False, indent=2)
                            saved = True
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(600)

                if not saved and last_cookies and self.is_valid_mytoon_session(last_cookies):
                    with open(self.mytoon_session_path, "w", encoding="utf-8") as session_file:
                        json.dump(last_cookies, session_file, ensure_ascii=False, indent=2)
                    saved = True

                if saved:
                    self.cached_mytoon_data = None
                    self.after(0, self.log, "MyToon session амжилттай хадгалагдлаа.")
                    self.after(0, lambda: messagebox.showinfo("MyToon", "Нэвтрэлт амжилттай! Одоо VIP бүлгүүдээ татах боломжтой."))
                else:
                    self.after(0, self.log, "MyToon нэвтрэлт баталгаажсангүй эсвэл browser хаагдлаа.")
                    self.after(0, lambda: messagebox.showwarning("MyToon", "Нэвтрэлт хийгдээгүй байна. Дахин 'MYTOON НЭВТРЭХ' дарж нэвтэрнэ үү."))

                try:
                    context.close()
                except Exception:
                    pass
                context = None
        except Exception as err:
            self.after(0, self.log, f"MyToon login алдаа: {err}")
            self.after(0, lambda e=str(err): messagebox.showerror("MyToon login", e))
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            self.after(0, lambda: (self.mytoon_login_button.configure(state="normal", text="MYTOON НЭВТРЭХ"), self.refresh_session_badges()))

    def start_nebula_login(self):
        if sync_playwright is None:
            messagebox.showerror("Playwright алга", "Playwright суулгаагүй тул Nebula login browser нээж чадсангүй.")
            return
        self.nebula_login_button.configure(state="disabled", text="BROWSER НЭЭЖ БАЙНА...")
        threading.Thread(target=self.run_nebula_login, daemon=True).start()

    def start_manga_mn_login(self):
        target_url = self.normalize_input_url(self.url_entry.get().strip())
        if "manga.mn" not in target_url.lower():
            target_url = "https://manga.mn/"
        existing_cookies = []
        try:
            with open(self.manga_mn_session_path, "r", encoding="utf-8") as session_file:
                existing_cookies = json.load(session_file)
        except (OSError, ValueError, TypeError):
            existing_cookies = []
        if self.verify_manga_mn_session_cookies(existing_cookies, target_url):
            self.log("manga.mn session is already valid.")
            messagebox.showinfo("manga.mn", "Already logged in. You can close the Google login window.")
            return
        if sync_playwright is None:
            messagebox.showerror("Playwright missing", "Playwright is not installed, so the manga.mn login browser cannot open.")
            return
        self.manga_mn_login_button.configure(state="disabled", text="OPENING BROWSER...")
        threading.Thread(target=self.run_manga_mn_login, args=(target_url,), daemon=True).start()

    def run_nebula_login(self):
        try:
            os.makedirs(os.path.dirname(self.nebula_session_path), exist_ok=True)
            self.after(0, self.log, "Nebula login browser нээгдлээ. Аккаунтаараа нэвтэрнэ үү.")
            with sync_playwright() as playwright:
                browser = self.launch_any_browser(playwright, headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://nebula.mn/login", wait_until="domcontentloaded", timeout=60000)

                deadline = time.time() + 300
                logged_in = False
                while time.time() < deadline:
                    if page.is_closed():
                        break
                    cookies = context.cookies("https://nebula.mn")
                    has_login_cookie = any(
                        cookie.get("name", "").startswith("wordpress_logged_in_")
                        for cookie in cookies
                    )
                    if has_login_cookie or "/profile" in page.url:
                        with open(self.nebula_session_path, "w", encoding="utf-8") as session_file:
                            json.dump(cookies, session_file, ensure_ascii=False, indent=2)
                        logged_in = True
                        break
                    page.wait_for_timeout(500)

                if logged_in:
                    self.after(0, self.log, "Nebula session амжилттай хадгалагдлаа.")
                    self.after(0, lambda: messagebox.showinfo("Nebula", "Нэвтрэлт амжилттай. Crown бүлэг татаж болно."))
                    page.wait_for_timeout(1000)
                else:
                    self.after(0, self.log, "Nebula нэвтрэлт дуусаагүй эсвэл browser хаагдлаа.")
                browser.close()
        except Exception as err:
            self.after(0, self.log, f"Nebula login алдаа: {err}")
            self.after(0, lambda e=str(err): messagebox.showerror("Nebula login", e))
        finally:
            self.after(0, lambda: (self.nebula_login_button.configure(state="normal", text="NEBULA НЭВТРЭХ"), self.refresh_session_badges()))

    def is_manga_mn_logged_in_page(self, page):
        body_text = page.locator("body").inner_text(timeout=2000).lower()
        login_prompt = "зөвхөн бүртгэлтэй хэрэглэгчдэд" in body_text or "нэвтэрч орж уншина уу" in body_text
        auth_action = "бүртгэлээрээ нэвтрэх" in body_text or "бүртгүүлэх" in body_text
        return not login_prompt and not auth_action

    def verify_manga_mn_session_cookies(self, cookies, target_url):
        if not cookies:
            return False
        cookie_map = {
            cookie["name"]: cookie["value"]
            for cookie in cookies
            if cookie.get("name") and cookie.get("value")
        }
        if not cookie_map:
            return False
        try:
            check_urls = [target_url]
            if target_url.rstrip("/") != "https://manga.mn":
                check_urls.append("https://manga.mn/")
            for check_url in check_urls:
                response = httpx.get(
                    check_url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    cookies=cookie_map,
                    follow_redirects=True,
                    timeout=20,
                )
                if response.status_code != 200:
                    continue
                soup = BeautifulSoup(response.text, "lxml")
                if soup.select_one(".nl-wrap"):
                    return False
                auth_links = [
                    link.get("href", "").lower()
                    for link in soup.find_all("a", href=True)
                ]
                return not any(href.endswith(("/auth/login", "/auth/register")) for href in auth_links)
            return False
        except Exception:
            return False

    def run_manga_mn_login(self, target_url):
        browser = None
        context = None
        try:
            os.makedirs(os.path.dirname(self.manga_mn_session_path), exist_ok=True)
            profile_dir = os.path.join(os.path.dirname(self.manga_mn_session_path), "manga_mn_chrome_profile")
            os.makedirs(profile_dir, exist_ok=True)
            self.after(0, self.log, "manga.mn login browser opened in Chrome. Log in manually, then close the browser to save.")
            with sync_playwright() as playwright:
                try:
                    context = playwright.chromium.launch_persistent_context(
                        profile_dir,
                        channel="chrome",
                        headless=False,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                except Exception:
                    self.after(0, self.log, "Chrome channel unavailable; falling back to bundled Chromium.")
                    browser = playwright.chromium.launch(headless=False)
                    context = browser.new_context()
                page = context.new_page()
                page.goto("https://manga.mn/auth/login", wait_until="domcontentloaded", timeout=60000)

                deadline = time.time() + 600
                latest_cookies = []
                while time.time() < deadline:
                    try:
                        if page.is_closed():
                            break
                        latest_cookies = context.cookies("https://manga.mn")
                        page.wait_for_timeout(500)
                    except Exception:
                        break

                if not latest_cookies:
                    try:
                        latest_cookies = context.cookies("https://manga.mn")
                    except Exception:
                        latest_cookies = []

                saved = self.verify_manga_mn_session_cookies(latest_cookies, target_url)
                if saved:
                    with open(self.manga_mn_session_path, "w", encoding="utf-8") as session_file:
                        json.dump(latest_cookies, session_file, ensure_ascii=False, indent=2)
                    self.after(0, self.log, "manga.mn session saved.")
                    self.after(0, lambda: messagebox.showinfo("manga.mn", "Login session saved."))
                else:
                    self.after(0, self.log, "manga.mn login was not confirmed. Session was not saved.")
                    self.after(0, lambda: messagebox.showwarning("manga.mn", "Login was not confirmed. Please log in fully, then close the browser."))

                try:
                    context.close()
                except Exception:
                    pass
                context = None
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                    browser = None
        except Exception as err:
            self.after(0, self.log, f"manga.mn login error: {err}")
            self.after(0, lambda e=str(err): messagebox.showerror("manga.mn login", e))
        finally:
            try:
                if context:
                    context.close()
            except Exception:
                pass
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            self.after(0, lambda: (self.manga_mn_login_button.configure(state="normal", text="MANGA.MN LOGIN"), self.refresh_session_badges()))

    def normalize_input_url(self, raw_url):
        url = "".join(raw_url.split())
        if not url:
            return ""

        lower_url = url.lower()

        # Fix corrupted schemes like ps://, ttps://, ttp://, etc.
        if re.match(r"^(?:https?//|[a-z]+://)", lower_url):
            if not lower_url.startswith(("http://", "https://")):
                colon_idx = url.find("://")
                if colon_idx != -1:
                    url = "https://" + url[colon_idx + 3:]
                    lower_url = url.lower()

        known_domains = list(self.direct_scraper_domains) + ["webtoons.com", "manga.mn", "mytoon.site"]

        if lower_url.startswith("https//"):
            url = "https://" + url[7:]
            lower_url = url.lower()
        elif lower_url.startswith("http//"):
            url = "http://" + url[6:]
            lower_url = url.lower()
        elif lower_url.startswith("https") and not lower_url.startswith("https://"):
            url = "https://" + url[5:]
            lower_url = url.lower()
        elif lower_url.startswith("http") and not lower_url.startswith(("http://", "https://")):
            url = "http://" + url[4:]
            lower_url = url.lower()

        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            for domain in known_domains:
                host_lower = parsed.netloc.lower()
                if domain in host_lower and not (host_lower == domain or host_lower.endswith("." + domain)):
                    domain_end = host_lower.index(domain) + len(domain)
                    fixed_host = parsed.netloc[:domain_end]
                    fixed_path = parsed.netloc[domain_end:] + parsed.path
                    fixed_url = f"{parsed.scheme}://{fixed_host}/{fixed_path.lstrip('/')}"
                    if parsed.query:
                        fixed_url += f"?{parsed.query}"
                    if parsed.fragment:
                        fixed_url += f"#{parsed.fragment}"
                    return self.restore_known_site_path(fixed_url)
            return self.restore_known_site_path(url)

        for domain in known_domains:
            marker = domain.replace(".", r"\.")
            match = re.search(marker, url, flags=re.IGNORECASE)
            if not match:
                continue

            prefix = "https://"
            host = url[:match.end()]
            path = url[match.end():]
            if "://" in host:
                host = host.split("://")[-1]
                url = prefix + host + path
            elif host.lower().startswith(("http://", "https://")):
                url = host + path
            else:
                url = prefix + host + path
            return self.restore_known_site_path(url)

        if lower_url.startswith("manhwa/") or "/viewer/" in lower_url:
            return "https://www.webtoons.com/en/" + url.lstrip("/")
        return url

    def restore_known_site_path(self, url):
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path

        if "mgeko.cc" in host:
            if path.startswith("/readeren/"):
                path = "/reader/en/" + path[len("/readeren/"):]
            elif path.startswith("readeren/"):
                path = "/reader/en/" + path[len("readeren/"):]
            elif path.startswith("/readeren"):
                path = "/reader/en/" + path[len("/readeren"):]
            elif path.startswith("readeren"):
                path = "/reader/en/" + path[len("readeren"):]

        if "mytoon.site" in host or "manga.mn" in host:
            if path.endswith("/"):
                path = path.rstrip("/")
        else:
            if path and not path.endswith("/") and not parsed.query and not parsed.fragment:
                path += "/"

        rebuilt = f"{parsed.scheme}://{parsed.netloc}{path}"
        if parsed.query:
            rebuilt += f"?{parsed.query}"
        if parsed.fragment:
            rebuilt += f"#{parsed.fragment}"
        return rebuilt

    def is_mytoon_url(self, url):
        return "mytoon.site" in urlparse(url).netloc.lower()

    def extract_mytoon_data(self, url):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://mytoon.site/",
        }
        soup = None
        full_data = ""
        try:
            with httpx.Client(headers=headers, cookies=self.cookies_for_url(url), follow_redirects=True, timeout=15.0) as client:
                res = client.get(url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "lxml")
                    chunks = []
                    for s in soup.find_all("script"):
                        if not s.string:
                            continue
                        for match in re.finditer(r'self\.__next_f\.push\(\[(\d+),\s*"(.*)"\]\)\s*;?', s.string, re.DOTALL):
                            chunks.append(match.group(2))
                    full_data = "".join(chunks)
        except Exception:
            return None

        result = {
            "webtoon_id": None,
            "title": None,
            "chapter_title": None,
            "cover_url": None,
            "current_chapter_num": None,
            "current_chapter_id": None,
            "current_images": [],
            "all_chapters": {},
            "is_vip_blocked": False
        }

        read_match = re.search(r"/webtoon/(\d+)/read/(\d+)", url)
        main_match = re.search(r"/webtoon/(\d+)", url)
        if read_match:
            result["webtoon_id"] = int(read_match.group(1))
            result["current_chapter_id"] = int(read_match.group(2))
        elif main_match:
            result["webtoon_id"] = int(main_match.group(1))

        # 1. Parse initialWebtoon / webtoon
        wt_match = re.search(r'\\"(?:initialWebtoon|webtoon)\\"\s*:\s*(\{.*?\}(?=,\\"|\}\]))', full_data)
        if wt_match:
            raw_wt = wt_match.group(1).replace(r'\"', '"').replace(r'\/', '/')
            try:
                wt_data = json.loads(raw_wt)
                result["title"] = wt_data.get("title")
                result["cover_url"] = wt_data.get("image")
                result["webtoon_id"] = wt_data.get("id", result["webtoon_id"])
            except Exception:
                pass

        # 2. Parse initialChapter
        ch_match = re.search(r'\\"initialChapter\\":\s*(\{.*?\}(?=,\\"initialWebtoon\\"))', full_data)
        if ch_match:
            raw_ch = ch_match.group(1).replace(r'\"', '"').replace(r'\/', '/')
            try:
                ch_data = json.loads(raw_ch)
                result["current_chapter_num"] = ch_data.get("chapter_number")
                result["current_chapter_id"] = ch_data.get("id")
                result["chapter_title"] = ch_data.get("title") or f"Chapter {result['current_chapter_num']}"
                result["current_images"] = ch_data.get("images", [])
            except Exception:
                pass

        # 3. Check VIP blocked
        if r'\"initialIsVipBlocked\":true' in full_data or r'"initialIsVipBlocked":true' in full_data:
            result["is_vip_blocked"] = True

        # 4. Parse all chapters from RSC
        all_ch_match = re.search(r'\\"(?:initialAllChapters|chapters)\\"\s*:\s*(\[.*?\])', full_data)
        if all_ch_match:
            raw_all = all_ch_match.group(1).replace(r'\"', '"').replace(r'\/', '/')
            try:
                ch_list = json.loads(raw_all)
                for item in ch_list:
                    c_num = item.get("chapter_number") or item.get("order_index")
                    if c_num is not None:
                        result["all_chapters"][int(c_num)] = item
            except Exception:
                pass

        # 5. Extract chapters from HTML <a> links
        if soup:
            for a in soup.find_all("a", href=True):
                href = a["href"]
                m = re.search(r"/webtoon/(\d+)/read/(\d+)", href)
                if m:
                    w_id, ch_id = int(m.group(1)), int(m.group(2))
                    text = a.get_text(" ", strip=True)
                    ch_num_m = re.search(r"Chapter\s*(\d+)", text, re.IGNORECASE)
                    if ch_num_m:
                        ch_num = int(ch_num_m.group(1))
                        if ch_num not in result["all_chapters"]:
                            result["all_chapters"][ch_num] = {
                                "id": ch_id,
                                "webtoon_id": w_id,
                                "chapter_number": ch_num,
                                "title": f"Chapter {ch_num}",
                                "url": f"https://mytoon.site{href}"
                            }

        # Fallback for title/cover from soup
        if not result["title"] and soup:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                result["title"] = og_title["content"]
            elif soup.title:
                t = soup.title.get_text().replace(" | WEBTOON", "").replace(" - WEBTOON", "").strip()
                if t and t != "Уншиж байна...":
                    result["title"] = t

        if not result["cover_url"] and soup:
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                result["cover_url"] = og_img["content"]

        return result

    def is_manga_mn_url(self, url):
        host = urlparse(url).netloc.lower()
        return host == "manga.mn" or host.endswith(".manga.mn")

    def parse_manga_mn_url_parts(self, url):
        path = unquote(urlparse(url).path).strip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "manga":
            series_slug = parts[1]
            chapter_slug = parts[2] if len(parts) >= 3 else None
            return series_slug, chapter_slug
        return None, None

    def parse_manga_mn_chapter_number(self, chapter_slug, label=""):
        if label:
            m = re.search(r"(?:ch\.?|chapter|volume|vol\.?|бүлэг|#)\s*0*(\d+)", label, flags=re.IGNORECASE)
            if m:
                return int(m.group(1))
        if chapter_slug:
            m = re.search(r"(?:ch|chapter|c)[._\-]*(\d+)", chapter_slug, flags=re.IGNORECASE)
            if m:
                return int(m.group(1))
            m = re.search(r"(\d+)", chapter_slug)
            if m:
                return int(m.group(1))
        return None

    def extract_manga_mn_reader_images(self, soup, page_url):
        image_urls = []
        seen = set()

        def normalize_img_url(raw_src):
            if not raw_src:
                return None
            src = raw_src.strip()
            if not src or src == "0" or src.startswith("data:"):
                return None
            full = urljoin(page_url, src)
            full = re.sub(r"(https?://[^/]+)//+", r"\1/", full)
            return full

        candidates = soup.select("main#canvas figure.page img, #canvas img, .page-img img, #all img")
        if not candidates:
            candidates = [
                im for im in soup.find_all("img")
                if "/chapters/" in ((im.get("src") or im.get("data-src") or ""))
            ]

        for img in candidates:
            raw = img.get("data-src") or img.get("src") or ""
            full_url = normalize_img_url(raw)
            if not full_url:
                continue
            lower_url = full_url.lower()
            if any(skip in lower_url for skip in ("zuragtnom-logo", "favicon", "/cover/")):
                continue
            if full_url not in seen:
                seen.add(full_url)
                image_urls.append(full_url)
        return image_urls

    def extract_manga_mn_data(self, url):
        series_slug, chapter_slug = self.parse_manga_mn_url_parts(url)
        if not series_slug:
            return None

        series_url = f"https://manga.mn/manga/{series_slug}"
        target_url = f"{series_url}/{chapter_slug}" if chapter_slug else series_url
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://manga.mn/",
        }
        cookies = self.cookies_for_url(url)

        result = {
            "series_slug": series_slug,
            "series_url": series_url,
            "title": None,
            "cover_url": f"https://manga.mn/uploads/manga/{series_slug}/cover/cover_250x350.jpg",
            "current_chapter_slug": chapter_slug,
            "current_chapter_num": self.parse_manga_mn_chapter_number(chapter_slug) if chapter_slug else None,
            "current_chapter_url": f"{series_url}/{chapter_slug}" if chapter_slug else None,
            "current_images": [],
            "all_chapters": {},
            "is_login_required": False,
        }

        def is_blocked_soup(sp):
            if sp.select_one(".nl-wrap"):
                return True
            auth_hrefs = [a.get("href", "").lower() for a in sp.find_all("a", href=True)]
            return any(h.endswith(("/auth/login", "/auth/register")) for h in auth_hrefs)

        def collect_chapters_from_soup(sp):
            for opt in sp.select("#chapterSelect option[value]"):
                val = opt.get("value", "").strip()
                _, ch_s = self.parse_manga_mn_url_parts(val)
                if not ch_s:
                    continue
                label = opt.get_text(" ", strip=True)
                ch_n = self.parse_manga_mn_chapter_number(ch_s, label)
                if ch_n is not None:
                    full_ch_url = f"{series_url}/{ch_s}"
                    result["all_chapters"][ch_n] = full_ch_url
                    if chapter_slug and ch_s.lower() == chapter_slug.lower():
                        result["current_chapter_num"] = ch_n
                        result["current_chapter_url"] = full_ch_url

            for a in sp.find_all("a", href=True):
                href = a["href"].strip()
                s_slug, ch_s = self.parse_manga_mn_url_parts(urljoin("https://manga.mn/", href))
                if s_slug != series_slug or not ch_s:
                    continue
                # Ignore prev/next single-arrow pagination links
                label = a.get_text(" ", strip=True)
                if label in ("‹", "›", "«", "»"):
                    continue
                ch_n = self.parse_manga_mn_chapter_number(ch_s, label)
                if ch_n is not None and ch_n not in result["all_chapters"]:
                    result["all_chapters"][ch_n] = f"{series_url}/{ch_s}"

        try:
            with httpx.Client(headers=headers, cookies=cookies, follow_redirects=True, timeout=20.0) as client:
                res = client.get(target_url)
                if res.status_code == 200:
                    soup = BeautifulSoup(res.text, "lxml")
                    if is_blocked_soup(soup):
                        result["is_login_required"] = True
                        return result

                    collect_chapters_from_soup(soup)
                    if chapter_slug:
                        result["current_images"] = self.extract_manga_mn_reader_images(soup, target_url)

                    # Extract series title
                    for sel in ("h1.title", "a.brand", ".title", "h2.widget-title"):
                        el = soup.select_one(sel)
                        if el:
                            txt = el.get_text(" ", strip=True)
                            if txt and txt.lower() not in ("back to manga", "manga & comics"):
                                result["title"] = txt
                                break
                    if not result["title"] and soup.title:
                        result["title"] = soup.title.get_text(" ", strip=True)

                    for im in soup.find_all("img", src=True):
                        if "/cover/" in im["src"]:
                            full_cov = urljoin("https://manga.mn/", im["src"].strip())
                            result["cover_url"] = re.sub(r"(https?://[^/]+)//+", r"\1/", full_cov)
                            break

                # If chapter list wasn't on target page (or target chapter 500'd), check series page
                if not result["all_chapters"]:
                    s_res = client.get(series_url)
                    if s_res.status_code == 200:
                        s_soup = BeautifulSoup(s_res.text, "lxml")
                        if is_blocked_soup(s_soup):
                            result["is_login_required"] = True
                            return result
                        collect_chapters_from_soup(s_soup)
                        if not result["title"]:
                            h1 = s_soup.select_one("h1.title, .title")
                            if h1:
                                result["title"] = h1.get_text(" ", strip=True)
                elif res.status_code != 200 and not cookies:
                    result["is_login_required"] = True
        except Exception:
            return None

        if not result["title"]:
            result["title"] = series_slug
        return result

    def show_supported_sites(self):
        if self.supported_sites_window and self.supported_sites_window.winfo_exists():
            self.supported_sites_window.focus()
            return

        window = ctk.CTkToplevel(self)
        window.title("Дэмждэг сайтууд — MYTOON Pro Studio")
        window.geometry("780x600")
        window.configure(fg_color="#06070A")
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)
        self.supported_sites_window = window

        header_frame = ctk.CTkFrame(window, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=24, pady=(20, 12), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(
            header_frame, text="Дэмждэг болон шалгагдсан сайтууд",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="white", anchor="w"
        )
        header.grid(row=0, column=0, sticky="w")

        sub = ctk.CTkLabel(
            header_frame, text="Доорх сайтуудаас өндөр хурдаар шууд татна. 'Жишээ' товчоор туршиж болно.",
            font=ctk.CTkFont(family="Segoe UI", size=12), text_color=self.TEXT_MUTED, anchor="w"
        )
        sub.grid(row=1, column=0, sticky="w", pady=(2, 0))

        content = ctk.CTkScrollableFrame(
            window, fg_color=self.UCHIHA_BLACK, corner_radius=14,
            border_width=1, border_color=self.BORDER_SUBTLE
        )
        content.grid(row=1, column=0, padx=24, pady=(0, 16), sticky="nsew")
        content.grid_columnconfigure(0, weight=1)

        sites = [
            {
                "name": "MYTOON",
                "domain": "mytoon.site",
                "badge": "VIP + R2 CDN",
                "status": "Cloudflare R2 серверээс өндөр хурдаар шууд татна.",
                "range": "Бүлгүүдийн жагсаалтаас Start / End range бүрэн дэмжинэ (VIP эрхээр нэвтэрч болно).",
                "example": "https://mytoon.site/webtoon/116",
            },
            {
                "name": "MANGA.MN",
                "domain": "manga.mn",
                "badge": "LOGIN + FULL HD",
                "status": "MANGA.MN LOGIN хийсний дараа бүх зургийг эх чанараар шууд татна.",
                "range": "Бүлгүүдийн жагсаалтаас Start / End chapter range (1-20 гэх мэт) бүрэн дэмжинэ.",
                "example": "https://manga.mn/manga/greatest-dev",
            },
            {
                "name": "WEBTOONS",
                "domain": "webtoons.com",
                "badge": "NATIVE API",
                "status": "Албан ёсны Webtoons API ашиглан гадны программгүйгээр шууд татна.",
                "range": "Start / End бүх бүлгийн интервал дэмжинэ.",
                "example": "https://www.webtoons.com/en/fantasy/tower-of-god/list?title_no=95",
            },
            {
                "name": "NEBULA",
                "domain": "nebula.mn",
                "badge": "CROWN VIP",
                "status": "Reader доторх бүх зургийг шууд татна.",
                "range": "Бүлгийн жагсаалтаас Start / End chapter range дэмжинэ.",
                "example": "https://nebula.mn/chapter/бүлэг-1-48/",
            },
            {
                "name": "MANHUAUS",
                "domain": "manhuaus.com",
                "badge": "DIRECT",
                "status": "Асуудалгүй шалгасан: бүлгийн бүх зургийг шууд татна.",
                "range": "chapter-20 ... chapter-40 хэлбэрийн range дэмжинэ.",
                "example": "https://manhuaus.com/manga/",
            },
            {
                "name": "MGEKO",
                "domain": "mgeko.cc",
                "badge": "DIRECT",
                "status": "Асуудалгүй шалгасан: олон бүлгээр дарааллан татна.",
                "range": "chapter-1-eng-li ... chapter-40-eng-li хэлбэрийн range дэмжинэ.",
                "example": "https://www.mgeko.cc/",
            },
            {
                "name": "ASURA SCANS",
                "domain": "asurascans.com",
                "badge": "DIRECT",
                "status": "Асуудалгүй шалгасан: chapter URL-аас шууд татна.",
                "range": "chapter/195 хэлбэрийн chapter URL дэмжинэ.",
                "example": "https://asurascans.com/",
            },
            {
                "name": "HENTAI20",
                "domain": "hentai20.io",
                "badge": "DIRECT",
                "status": "Асуудалгүй шалгасан: chapter URL-аас шууд татна.",
                "range": "chapter-1 хэлбэрийн chapter URL дэмжинэ.",
                "example": "https://hentai20.io/",
            },
            {
                "name": "UNIVERSAL FALLBACK",
                "domain": "Бусад manga/manhwa сайтууд",
                "badge": "PLAYWRIGHT + MADARA",
                "status": "Madara болон headless browser горимоор автоматаар зургийг илрүүлж татна.",
                "range": "URL pattern тохирвол Start / End автоматаар ажиллана.",
                "example": "",
            },
        ]

        def use_example(ex_url):
            if not ex_url:
                return
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, ex_url)
            window.destroy()
            self.verify_url()

        for row, site in enumerate(sites):
            card = ctk.CTkFrame(
                content, fg_color=self.UCHIHA_GRAY, corner_radius=10,
                border_width=1, border_color=self.BORDER_SUBTLE
            )
            card.grid(row=row, column=0, padx=10, pady=6, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.grid(row=0, column=0, padx=14, pady=(10, 4), sticky="ew")
            top_row.grid_columnconfigure(0, weight=1)

            title = ctk.CTkLabel(
                top_row, text=f"{site['name']}   ·   {site['domain']}",
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                text_color="white", anchor="w"
            )
            title.grid(row=0, column=0, sticky="w")

            badge = ctk.CTkLabel(
                top_row, text=site["badge"], height=22, corner_radius=6,
                fg_color=self.SURFACE_ELEVATED, text_color="#60A5FA", padx=8,
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold")
            )
            badge.grid(row=0, column=1, padx=(8, 0), sticky="e")

            if site.get("example") and site["example"].startswith("http"):
                ex_btn = ctk.CTkButton(
                    top_row, text="Жишээ", width=64, height=22, corner_radius=6,
                    fg_color=self.UCHIHA_RED, hover_color=self.UCHIHA_DARK_RED,
                    font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
                    command=lambda u=site["example"]: use_example(u)
                )
                ex_btn.grid(row=0, column=2, padx=(8, 0), sticky="e")

            body_text = f"{site['status']}\n{site['range']}"
            if site.get("example"):
                body_text += f"\nЖишээ: {site['example']}"
            body = ctk.CTkLabel(
                card, text=body_text, justify="left", anchor="w",
                font=ctk.CTkFont(family="Segoe UI", size=12), text_color="#94A3B8",
                wraplength=660
            )
            body.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="ew")

        close_button = ctk.CTkButton(
            window, text="ХААХ", width=120, height=36, corner_radius=8,
            command=window.destroy, fg_color=self.UCHIHA_RED,
            hover_color=self.UCHIHA_DARK_RED, font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        )
        close_button.grid(row=2, column=0, padx=24, pady=(0, 18), sticky="e")

    def verify_url(self):
        url = self.normalize_input_url(self.url_entry.get())
        if not url:
            return

        # Smart Fix for common mistakes
        if not url.startswith("http"):
            if "webtoons.com" in url:
                url = "https://" + url
            elif "mytoon.site" in url or "manga.mn" in url:
                url = "https://" + url
            elif url.startswith("manhwa/") or "/viewer/" in url:
                url = "https://www.webtoons.com/en/" + url.lstrip("/")
            else:
                self.site_badge_label.configure(text="● БУРУУ ХАЯГ", text_color=self.ACCENT_AMBER)
                self.webtoon_name_label.configure(text="Анхаар: Бүтэн URL оруулна уу (https://...)", text_color=self.ACCENT_AMBER)
                return

        if url != self.url_entry.get().strip():
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)

        host_display = urlparse(url).netloc.upper().replace("WWW.", "") or "WEBTOON"
        self.site_badge_label.configure(text=f"● ШАЛГАЖ БАЙНА: {host_display}", text_color="#60A5FA")
        self.webtoon_name_label.configure(text="Мэдээлэл татаж байна...", text_color="white")

        def fetch():
            try:
                # 1. Dedicated handler for MYTOON.SITE
                if self.is_mytoon_url(url):
                    info = self.extract_mytoon_data(url)
                    self.cached_mytoon_data = info
                    if not info or not info.get("title"):
                        self.after(0, lambda: (
                            self.site_badge_label.configure(text="● MYTOON.SITE · ОЛДСОНГҮЙ", text_color=self.ACCENT_AMBER),
                            self.webtoon_name_label.configure(text="MyToon: Мэдээлэл олдсонгүй", text_color=self.ACCENT_AMBER)
                        ))
                        return

                    title = info["title"]
                    self.verified_series = {"url": url, "title": title}
                    ch_num = info.get("current_chapter_num")
                    all_ch = info.get("all_chapters", {})
                    if all_ch:
                        self.detected_min_chapter = min(all_ch.keys())
                        self.detected_max_chapter = max(all_ch.keys())

                    if ch_num:
                        desc = f"{title}\nБүлэг {ch_num}"
                        if info.get("is_vip_blocked"):
                            desc += " · VIP түгжээтэй"
                        elif info.get("current_images"):
                            desc += f" · {len(info['current_images'])} зураг"
                        self.after(0, lambda c=ch_num: (self.start_entry.delete(0, "end"), self.start_entry.insert(0, str(c))))
                        self.after(0, lambda c=ch_num: (self.end_entry.delete(0, "end"), self.end_entry.insert(0, str(c))))
                    elif all_ch:
                        min_c = min(all_ch.keys())
                        max_c = max(all_ch.keys())
                        desc = f"{title}\nНийт {len(all_ch)} бүлэг ({min_c}–{max_c})"
                        self.after(0, lambda c=min_c: (self.start_entry.delete(0, "end"), self.start_entry.insert(0, str(c))))
                        self.after(0, lambda c=max_c: (self.end_entry.delete(0, "end"), self.end_entry.insert(0, str(c))))
                    else:
                        desc = f"{title}"

                    cover_url = info.get("cover_url")
                    if cover_url:
                        try:
                            headers = {"User-Agent": "Mozilla/5.0"}
                            with httpx.Client(timeout=10.0, follow_redirects=True) as img_client:
                                img_res = img_client.get(cover_url, headers=headers)
                                if img_res.status_code == 200:
                                    img_data = Image.open(io.BytesIO(img_res.content))
                                    img_data = ImageOps.fit(img_data, (280, 136), Image.Resampling.LANCZOS)
                                    ctk_img = ctk.CTkImage(light_image=img_data, dark_image=img_data, size=(280, 136))
                                    self.after(0, lambda: self.preview_image_label.configure(image=ctk_img, text=""))
                        except Exception:
                            pass

                    self.after(0, lambda d=desc: (
                        self.site_badge_label.configure(text="● MYTOON.SITE · БЭЛЭН", text_color=self.ACCENT_GREEN),
                        self.webtoon_name_label.configure(text=d, text_color="white")
                    ))
                    return

                # 1b. Dedicated handler for MANGA.MN
                if self.is_manga_mn_url(url):
                    info = self.extract_manga_mn_data(url)
                    self.cached_manga_mn_data = info
                    if not info:
                        self.after(0, lambda: (
                            self.site_badge_label.configure(text="● MANGA.MN · ОЛДСОНГҮЙ", text_color=self.ACCENT_AMBER),
                            self.webtoon_name_label.configure(text="manga.mn: Мэдээлэл олдсонгүй", text_color=self.ACCENT_AMBER)
                        ))
                        return
                    if info.get("is_login_required"):
                        self.after(0, lambda: (
                            self.site_badge_label.configure(text="● MANGA.MN · НЭВТРЭХ ШААРДЛАГАТАЙ", text_color=self.ACCENT_AMBER),
                            self.webtoon_name_label.configure(
                                text="manga.mn: Нэвтрэх шаардлагатай\n(MANGA.MN НЭВТРЭХ дарна уу)",
                                text_color=self.ACCENT_AMBER,
                            )
                        ))
                        return

                    title = info.get("title") or "manga.mn"
                    self.verified_series = {"url": url, "title": title}
                    ch_num = info.get("current_chapter_num")
                    all_ch = info.get("all_chapters", {})
                    if all_ch:
                        self.detected_min_chapter = min(all_ch.keys())
                        self.detected_max_chapter = max(all_ch.keys())

                    if ch_num is not None:
                        desc = f"{title}\nБүлэг {ch_num}"
                        if info.get("current_images"):
                            desc += f" ({len(info['current_images'])} зураг)"
                        if all_ch:
                            desc += f" · Нийт {len(all_ch)} бүлэг"
                        self.after(0, lambda c=ch_num: (self.start_entry.delete(0, "end"), self.start_entry.insert(0, str(c))))
                        self.after(0, lambda c=ch_num: (self.end_entry.delete(0, "end"), self.end_entry.insert(0, str(c))))
                    elif all_ch:
                        min_c = min(all_ch.keys())
                        max_c = max(all_ch.keys())
                        desc = f"{title}\nНийт {len(all_ch)} бүлэг ({min_c}–{max_c})"
                        self.after(0, lambda c=min_c: (self.start_entry.delete(0, "end"), self.start_entry.insert(0, str(c))))
                        self.after(0, lambda c=max_c: (self.end_entry.delete(0, "end"), self.end_entry.insert(0, str(c))))
                    else:
                        desc = f"{title}"

                    cover_url = info.get("cover_url")
                    if cover_url:
                        try:
                            headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://manga.mn/"}
                            with httpx.Client(cookies=self.cookies_for_url(url), timeout=10.0, follow_redirects=True) as img_client:
                                img_res = img_client.get(cover_url, headers=headers)
                                if img_res.status_code == 200 and len(img_res.content) > 500:
                                    img_data = Image.open(io.BytesIO(img_res.content))
                                    img_data = ImageOps.fit(img_data, (280, 136), Image.Resampling.LANCZOS)
                                    ctk_img = ctk.CTkImage(light_image=img_data, dark_image=img_data, size=(280, 136))
                                    self.after(0, lambda: self.preview_image_label.configure(image=ctk_img, text=""))
                        except Exception:
                            pass

                    self.after(0, lambda d=desc: (
                        self.site_badge_label.configure(text="● MANGA.MN · БЭЛЭН", text_color=self.ACCENT_GREEN),
                        self.webtoon_name_label.configure(text=d, text_color="white")
                    ))
                    return

                # 1c. Dedicated handler for WEBTOONS.COM series list
                if "webtoons.com" in url.lower() and not self.is_webtoons_viewer_url(url) and "title_no=" in url.lower():
                    try:
                        wt_title, wt_eps = self.fetch_webtoons_episodes(url)
                        if wt_eps:
                            wt_title = wt_title or self.guess_series_title(url)
                            self.verified_series = {"url": url, "title": wt_title}
                            self.detected_min_chapter = 1
                            self.detected_max_chapter = len(wt_eps)
                            desc = f"{wt_title}\nНийт {len(wt_eps)} бүлэг (1–{len(wt_eps)})"
                            self.after(0, lambda: (self.start_entry.delete(0, "end"), self.start_entry.insert(0, "1")))
                            self.after(0, lambda m=len(wt_eps): (self.end_entry.delete(0, "end"), self.end_entry.insert(0, str(m))))
                            self.after(0, lambda d=desc: (
                                self.site_badge_label.configure(text="● WEBTOONS.COM · БЭЛЭН", text_color=self.ACCENT_GREEN),
                                self.webtoon_name_label.configure(text=d, text_color="white")
                            ))
                            return
                    except Exception:
                        pass

                # 2. Generic / Other sites
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://www.google.com/",
                }
                with httpx.Client(follow_redirects=True, timeout=12.0, headers=headers, cookies=self.cookies_for_url(url), verify=not self.should_skip_tls_verify(url)) as client:
                    response = client.get(url)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, "lxml")
                        title_tag = soup.find("meta", property="og:title")
                        reader = soup.select_one("#nkBody[data-manga-title]")
                        page_title = soup.find("title")

                        if title_tag and title_tag.get("content"):
                            title = title_tag["content"]
                        elif reader and reader.get("data-manga-title"):
                            title = reader["data-manga-title"]
                        elif page_title:
                            title = page_title.get_text(" ", strip=True)
                        else:
                            title = "Хуудас олдлоо"

                        series_title = reader.get("data-manga-title") if reader and reader.get("data-manga-title") else title
                        self.verified_series = {"url": url, "title": self.clean_series_title(series_title, url)}

                        if "nebula.mn" in urlparse(url).netloc.lower():
                            locked = soup.select_one("#nkLocked") is not None
                            image_count = len(self.extract_reader_images(soup, url))
                            neb_chs = self.extract_nebula_chapter_urls(soup, url)
                            if neb_chs:
                                self.detected_min_chapter = min(neb_chs.keys())
                                self.detected_max_chapter = max(neb_chs.keys())
                            access = "Crown session шаардлагатай" if locked else f"{image_count} зураг"
                            title = f"{title}\n{access}"

                        # Try cover
                        img_tag = soup.find("meta", property="og:image")
                        if img_tag and img_tag.get("content"):
                            try:
                                img_res = client.get(img_tag["content"])
                                if img_res.status_code == 200:
                                    img_data = Image.open(io.BytesIO(img_res.content))
                                    img_data = ImageOps.fit(img_data, (280, 136), Image.Resampling.LANCZOS)
                                    ctk_img = ctk.CTkImage(light_image=img_data, dark_image=img_data, size=(280, 136))
                                    self.after(0, lambda: self.preview_image_label.configure(image=ctk_img, text=""))
                            except Exception:
                                pass

                        ch_extracted = self.extract_chapter_number(url)
                        if ch_extracted:
                            self.after(0, lambda c=ch_extracted: (self.start_entry.delete(0, "end"), self.start_entry.insert(0, str(c))))
                            self.after(0, lambda c=ch_extracted: (self.end_entry.delete(0, "end"), self.end_entry.insert(0, str(c))))

                        self.after(0, lambda t=title, h=host_display: (
                            self.site_badge_label.configure(text=f"● {h} · БЭЛЭН", text_color=self.ACCENT_GREEN),
                            self.webtoon_name_label.configure(text=t, text_color="white")
                        ))
                    else:
                        if self.should_use_direct_scraper(url) or self.is_webtoons_viewer_url(url):
                            self.after(0, lambda h=host_display: (
                                self.site_badge_label.configure(text=f"● {h} · DIRECT SCRAPER", text_color="#60A5FA"),
                                self.webtoon_name_label.configure(text="Direct scraper горимоор татах боломжтой", text_color="#93C5FD")
                            ))
                        elif "webtoons.com" not in url.lower():
                            self.after(0, lambda h=host_display: (
                                self.site_badge_label.configure(text=f"● {h} · UNIVERSAL", text_color="#60A5FA"),
                                self.webtoon_name_label.configure(text="Universal горимоор татах боломжтой", text_color="#93C5FD")
                            ))
                        else:
                            self.after(0, lambda code=response.status_code: (
                                self.site_badge_label.configure(text=f"● HTTP {code}", text_color=self.ACCENT_AMBER),
                                self.webtoon_name_label.configure(text=f"Алдаа: {code}", text_color=self.ACCENT_AMBER)
                            ))
            except Exception as e:
                if self.should_use_direct_scraper(url) or self.is_webtoons_viewer_url(url):
                    self.after(0, lambda: self.webtoon_name_label.configure(text="Direct scraper горимоор татаж үзнэ", text_color="#93C5FD"))
                elif "webtoons.com" not in url.lower():
                    self.after(0, lambda: self.webtoon_name_label.configure(text="Universal горимоор татаж үзнэ үү", text_color="#93C5FD"))
                else:
                    self.after(0, lambda err=str(e): self.webtoon_name_label.configure(text=f"Холболтын алдаа: {err}", text_color=self.ACCENT_AMBER))

        threading.Thread(target=fetch, daemon=True).start()

    def start_download(self):
        if self.downloading:
            return
        url = self.normalize_input_url(self.url_entry.get())
        if not url:
            messagebox.showerror("Алдаа", "URL хаяг оруулна уу")
            return

        if url != self.url_entry.get().strip():
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)

        start_str = self.start_entry.get().strip()
        end_str = self.end_entry.get().strip()
        save_as = self.format_combo.get()
        save_path = self.path_entry.get().strip() or DEFAULT_SETTINGS["save_path"]

        # Snapshot UI settings on the main thread (Tk widgets must not be read from worker threads)
        self.current_save_path = save_path
        self.current_save_as = save_as
        try:
            self.current_workers = max(1, min(32, int(self.workers_combo.get())))
        except (TypeError, ValueError):
            self.current_workers = 4
        self.current_skip_existing = bool(self.skip_existing_var.get())
        self.current_delete_after = bool(self.delete_after_var.get())
        self.save_settings()
        try:
            os.makedirs(save_path, exist_ok=True)
        except OSError as err:
            messagebox.showerror("Алдаа", f"Хадгалах хавтас үүсгэж чадсангүй:\n{err}")
            return

        chapter_from_url = self.extract_chapter_number(url)

        try:
            if chapter_from_url and (not start_str or start_str == "1") and not end_str:
                self.current_start_ch = chapter_from_url
            else:
                self.current_start_ch = int(start_str) if start_str else (chapter_from_url or 1)
            self.current_end_ch = int(end_str) if end_str and end_str.isdigit() else self.current_start_ch
            if self.current_end_ch < self.current_start_ch:
                self.current_start_ch, self.current_end_ch = self.current_end_ch, self.current_start_ch
            self.current_total_chapters = self.current_end_ch - self.current_start_ch + 1
        except Exception:
            self.current_start_ch = chapter_from_url or 1
            self.current_end_ch = self.current_start_ch
            self.current_total_chapters = 1

        is_webtoons = "webtoons.com" in url.lower()
        is_webtoons_viewer = self.is_webtoons_viewer_url(url)
        is_manga_mn = "manga.mn" in urlparse(url).netloc.lower()
        is_manhwaread = "manhwaread.com" in urlparse(url).netloc.lower()
        is_mytoon = self.is_mytoon_url(url)
        is_direct_scraper = is_manhwaread or self.should_use_direct_scraper(url)

        if is_mytoon:
            engine_name = "MYTOON Direct Scraper"
            args = ["mytoon", url]
        elif is_manga_mn:
            engine_name = "MANGA.MN Direct Scraper"
            args = ["manga-mn", url]
        elif is_webtoons and not is_webtoons_viewer:
            engine_name = "WEBTOONS Native Scraper"
            args = ["webtoons", url]
        elif is_direct_scraper or is_webtoons_viewer:
            engine_name = "Direct scraper"
            args = ["direct-scraper", url]
        elif self.gallery_dl_path:
            engine_name = "gallery-dl"
            args = [self.gallery_dl_path, url]
            if "manhwa" in url.lower() or "manhua" in url.lower():
                args.extend(["-o", "extractor.madara.domain=" + url.split("/")[2]])
            if start_str or end_str:
                args.extend(["--range", f"{start_str if start_str else ''}-{end_str if end_str else ''}"])
            args.extend(["--directory", self.series_dir(self.guess_series_title(url))])
        else:
            engine_name = "Universal scraper (gallery-dl олдсонгүй)"
            args = ["direct-scraper", url]

        self.cancel_event.clear()
        self.download_button.configure(state="disabled", text="⏳  ТАТАЖ БАЙНА...", fg_color="#252B3B")
        self.cancel_button.configure(state="normal", text="ЗОГСООХ", fg_color=self.UCHIHA_DARK_RED, border_color=self.UCHIHA_RED)
        self.set_app_state("running")
        self.update_progress(0)
        self.stats_label.configure(text="Эхэлж байна...")
        self.downloading = True
        self.log(f"Эхлүүлж байна: {url}")
        self.log(f"Engine: {engine_name}")

        threading.Thread(target=self.run_downloader, args=(args,), daemon=True).start()

    def run_downloader(self, args):
        url = args[1]
        is_webtoons = "webtoons.com" in url.lower()
        try:
            if args[0] == "mytoon":
                self.run_mytoon_scraper(url)
                return

            if args[0] == "manga-mn":
                self.run_manga_mn_scraper(url)
                return

            if args[0] == "webtoons":
                if self.run_webtoons_scraper(url):
                    return
                if not self.downloader_path or self.cancel_event.is_set():
                    return
                self.after(0, lambda: self.log("Native scraper амжилтгүй. webtoon-downloader CLI-аар оролдож байна..."))
                args = [self.downloader_path, url,
                        "--start", str(self.current_start_ch), "--end", str(self.current_end_ch),
                        "--out", self.current_save_path]
                if self.current_save_as != "images":
                    args.extend(["--save-as", self.current_save_as])

            if args[0] == "direct-scraper" or (not is_webtoons and self.should_use_direct_scraper(url)):
                self.run_madara_scraper(url)
                return

            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, bufsize=1)
            self.current_process = process
            for line in process.stdout:
                clean = line.strip().replace('\r', '\n')
                for sl in clean.split('\n'):
                    if sl: self.after(0, self.log, sl)
            process.wait()
            self.current_process = None
            if self.cancel_event.is_set():
                self.after(0, lambda: self.log("Таталтыг хэрэглэгч зогсоолоо."))
            elif process.returncode == 0:
                self.after(0, lambda: self.update_progress(100))
                self.after(0, lambda: messagebox.showinfo("Амжилттай", "Татах ажиллагаа дууслаа!"))
            else:
                self.after(0, lambda: self.log("Үндсэн систем амжилтгүй. Нөөц системээр оролдож байна..."))
                self.run_madara_scraper(url)
        except DownloadCancelled:
            self.after(0, lambda: self.log("Таталтыг хэрэглэгч зогсоолоо."))
        except Exception as e:
            self.current_process = None
            if not is_webtoons and not self.cancel_event.is_set():
                self.after(0, lambda err=str(e): self.log(f"Universal fallback: {err}"))
                self.run_madara_scraper(url)
            else:
                self.after(0, lambda err=str(e): messagebox.showerror("Системийн алдаа", err))
        finally:
            self.current_process = None
            self.after(0, self.reset_ui)

    # ------------------------------------------------------------------
    # WEBTOONS (native, no external CLI required)
    # ------------------------------------------------------------------
    def fetch_webtoons_episodes(self, series_url):
        """Return (series_title, [viewer_url, ...]) using the public m.webtoons.com episode API."""
        parsed = urlparse(series_url)
        match = re.search(r"title_no=(\d+)", parsed.query)
        if not match:
            return None, []
        title_no = match.group(1)
        kind = "canvas" if ("/canvas/" in parsed.path.lower() or "/challenge/" in parsed.path.lower()) else "webtoon"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Safari/604.1",
            "Referer": "https://m.webtoons.com/",
        }
        title = None
        with httpx.Client(headers=headers, follow_redirects=True, timeout=30.0) as client:
            res = client.get(f"https://m.webtoons.com/api/v1/{kind}/{title_no}/episodes?pageSize=99999")
            res.raise_for_status()
            episodes = res.json().get("result", {}).get("episodeList", []) or []
            try:
                page = client.get(series_url.replace("://m.", "://www."), headers={"User-Agent": "Mozilla/5.0"})
                og = BeautifulSoup(page.text, "lxml").find("meta", property="og:title")
                if og and og.get("content"):
                    title = og["content"].strip()
            except Exception:
                pass
        urls = [f"https://www.webtoons.com{ep['viewerLink']}" for ep in episodes if ep.get("viewerLink")]
        return title, urls

    def run_webtoons_scraper(self, url):
        start, end = self.current_start_ch, self.current_end_ch
        try:
            title, viewer_urls = self.fetch_webtoons_episodes(url)
        except Exception as err:
            self.after(0, lambda e=str(err): self.log(f"Webtoons бүлгийн жагсаалт авч чадсангүй: {e}"))
            return False
        if not viewer_urls:
            self.after(0, lambda: self.log("Webtoons: бүлэг олдсонгүй (URL-д title_no= байгаа эсэхийг шалгана уу)."))
            return False

        title = title or self.guess_series_title(url)
        series_folder = self.series_dir(title)
        end = min(end, len(viewer_urls))
        total = max(1, end - start + 1)
        self.after(0, lambda: self.log(f"WEBTOONS: '{title}' — нийт {len(viewer_urls)} бүлэг, {start}-{end} татна."))
        self.begin_progress(total)

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        downloaded_any = False
        with httpx.Client(headers=headers, follow_redirects=True, timeout=30.0) as client:
            for idx, ch_num in enumerate(range(start, end + 1)):
                self.check_cancel()
                self.set_chapter_progress(idx, f"Бүлэг {ch_num}")
                ch_url = viewer_urls[ch_num - 1]
                try:
                    res = client.get(ch_url)
                    soup = BeautifulSoup(res.text, "lxml")
                    image_urls = []
                    for img in soup.select("#_imageList img, .viewer_img img"):
                        src = img.get("data-url") or img.get("src")
                        if src and src.startswith("http") and src not in image_urls:
                            image_urls.append(src.replace("?type=q90", ""))
                except Exception as err:
                    self.after(0, lambda c=ch_num, e=str(err): self.log(f"Бүлэг {c}: алдаа {e}"))
                    continue
                if not image_urls:
                    self.after(0, lambda c=ch_num: self.log(f"Бүлэг {c}: зураг олдсонгүй."))
                    continue
                if self.download_chapter(series_folder, ch_num, image_urls, ch_url, headers):
                    downloaded_any = True

        self.finish_download(downloaded_any, series_folder)
        return downloaded_any

    # ------------------------------------------------------------------
    # Shared chapter pipeline: folder -> download -> convert -> progress
    # ------------------------------------------------------------------
    def download_chapter(self, series_folder, ch_num, image_urls, ch_url, headers, min_bytes=1000):
        self.check_cancel()
        self.after(0, lambda c=ch_num, n=len(image_urls): self.log(f"Бүлэг {c}: Нийт {n} зураг оллоо. Татаж байна..."))
        ch_folder = os.path.join(series_folder, f"Chapter {ch_num}")
        os.makedirs(ch_folder, exist_ok=True)
        if not self.current_skip_existing:
            self.clear_old_page_images(ch_folder)
        count = self.download_chapter_images(image_urls, ch_url, ch_folder, headers,
                                             max_workers=self.current_workers, min_bytes=min_bytes,
                                             ch_label=f"(#{ch_num})")
        if count <= 0:
            return False
        if self.current_save_as in ("cbz", "zip", "pdf"):
            self.convert_chapter_format(ch_folder, self.current_save_as, ch_num, series_folder)
        self.after(0, lambda c=ch_num, cnt=count, n=len(image_urls): self.log(f"Бүлэг {c} амжилттай: {cnt}/{n} зураг."))
        return True

    def finish_download(self, downloaded_any, folder=None, fail_msg=None):
        if self.cancel_event.is_set():
            self.after(0, lambda: (self.set_app_state("cancelled"), self.log("Таталтыг хэрэглэгч зогсоолоо.")))
            return
        if downloaded_any:
            self.after(0, lambda: (self.update_progress(100), self.set_app_state("done")))
            self.after(0, lambda f=folder: self.log(f"Хадгалсан хавтас: {f}"))
            self.after(0, lambda f=folder: self.ask_open_folder(f))
        else:
            msg = fail_msg or "Зураг татагдсангүй. Бүлэг түгжээтэй эсвэл сайт хандалтыг хааж байж болзошгүй."
            self.after(0, lambda m=msg: (self.set_app_state("warn"), self.log(m)))
            self.after(0, lambda m=msg: messagebox.showwarning("Анхаар", m))

    def ask_open_folder(self, folder):
        if messagebox.askyesno("Амжилттай", "Татах ажиллагаа дууслаа!\n\nТатсан хавтсыг нээх үү?"):
            self.last_output_dir = folder
            self.open_output_folder()

    def should_use_direct_scraper(self, url):
        host = urlparse(url).netloc.lower()
        return any(host == domain or host.endswith("." + domain) for domain in self.direct_scraper_domains)

    def should_skip_tls_verify(self, url):
        host = urlparse(url).netloc.lower()
        return host == "manhwaread.com" or host.endswith(".manhwaread.com") or host == "manread.xyz" or host.endswith(".manread.xyz")

    def is_webtoons_viewer_url(self, url):
        parsed = urlparse(url)
        return "webtoons.com" in parsed.netloc.lower() and ("/viewer" in parsed.path.lower() or "episode_no=" in parsed.query.lower())

    def extract_chapter_number(self, url):
        if "mytoon.site" in url.lower():
            if self.cached_mytoon_data and self.cached_mytoon_data.get("current_chapter_num"):
                return self.cached_mytoon_data["current_chapter_num"]
        if self.is_manga_mn_url(url):
            _, ch_slug = self.parse_manga_mn_url_parts(url)
            if ch_slug:
                return self.parse_manga_mn_chapter_number(ch_slug)
            return None
        match = re.search(r"(?:/|-)chapter[/-](\d+)(?:[/?#-]|$)", url, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        decoded_url = unquote(url)
        match = re.search(r"/chapter/бүлэг-(\d+)(?:-[^/?#]+)?/?$", decoded_url, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"[?&]episode_no=(\d+)(?:&|$)", url, flags=re.IGNORECASE)
        return int(match.group(1)) if match else None

    def extract_nebula_chapter_urls(self, soup, page_url):
        if "nebula.mn" not in urlparse(page_url).netloc.lower():
            return {}

        chapter_urls = {}
        for link in soup.select("#chDropdown a[href], a.nav-fixed-btn[href]"):
            label = link.get_text(" ", strip=True)
            match = re.search(r"Бүлэг\s*(\d+)", label, flags=re.IGNORECASE)
            chapter_url = urljoin(page_url, link["href"])
            chapter_number = int(match.group(1)) if match else self.extract_chapter_number(chapter_url)
            if chapter_number is not None:
                chapter_urls[chapter_number] = chapter_url

        current = self.extract_chapter_number(page_url)
        if current is not None:
            chapter_urls.setdefault(current, page_url)
        return chapter_urls

    def build_chapter_url_patterns(self, url, base_url, ch_num):
        patterns = []
        chapter_match = re.search(r"(?i)(chapter[/-])(\d+)", url)
        padded_ch_num = str(ch_num)
        if chapter_match:
            original_digits = chapter_match.group(2)
            if original_digits.startswith("0"):
                padded_ch_num = str(ch_num).zfill(len(original_digits))
            replaced_url = re.sub(
                r"(?i)(chapter[/-])\d+",
                lambda match: f"{match.group(1)}{padded_ch_num}",
                url,
                count=1,
            )
            patterns.append(replaced_url)
        elif self.extract_chapter_number(url):
            replaced_url = url
            replaced_url = re.sub(
                r"(?i)([?&]episode_no=)\d+",
                lambda match: f"{match.group(1)}{ch_num}",
                replaced_url,
                count=1,
            )
            replaced_url = re.sub(
                r"(?i)(/ep-)\d+",
                lambda match: f"{match.group(1)}{ch_num}",
                replaced_url,
                count=1,
            )
            patterns.append(replaced_url)

        patterns.extend([
            f"{base_url}chapter-{padded_ch_num}/",
            f"{base_url}chapter-{ch_num}/",
            f"{base_url}chapter/{ch_num}/",
            f"{base_url}ch-{ch_num}/",
            f"{base_url}chapter-{ch_num}-eng-li/",
        ])

        unique_patterns = []
        for pattern in patterns:
            if pattern not in unique_patterns:
                unique_patterns.append(pattern)
        return unique_patterns

    def normalize_image_url(self, raw_url, page_url):
        if not raw_url:
            return None
        if isinstance(raw_url, list):
            raw_url = raw_url[0] if raw_url else ""
        raw_url = str(raw_url).replace("\n", " ").replace("\t", " ").strip()
        raw_url = raw_url.split(",")[0].split(" ")[0].strip()
        if not raw_url or raw_url.startswith("data:"):
            return None
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        return urljoin(page_url, raw_url)

    def get_image_src(self, img, page_url):
        possible_srcs = [
            img.get("data-src"),
            img.get("data-lazy-src"),
            img.get("data-cfsrc"),
            img.get("data-src-optimized"),
            img.get("data-original"),
            img.get("data-original-src"),
            img.get("data-url"),
            img.get("src"),
            img.get("srcset"),
        ]
        for p_src in possible_srcs:
            src = self.normalize_image_url(p_src, page_url)
            if src and src.startswith("http") and not any(x in src.lower() for x in ["logo", "banner", "button", "avatar", "icon", "readerarea", ".svg"]):
                return src
        return None

    def extract_chapter_data_images(self, soup, page_url):
        html = str(soup)
        match = re.search(r"var\s+chapterData\s*=\s*(\{.*?\});", html, flags=re.DOTALL)
        if not match:
            return []

        try:
            chapter_data = json.loads(match.group(1))
            encoded = chapter_data.get("data")
            base = chapter_data.get("base") or page_url
            if not encoded:
                return []

            padding = "=" * (-len(encoded) % 4)
            pages = json.loads(base64.b64decode(encoded + padding).decode("utf-8"))
        except Exception:
            return []

        image_urls = []
        seen = set()
        for page in pages:
            if not isinstance(page, dict):
                continue
            src = self.normalize_image_url(page.get("src"), base.rstrip("/") + "/")
            width = int(page.get("w") or 0)
            height = int(page.get("h") or 0)
            if not src or src in seen:
                continue
            if width and height and (width < 300 or height < 800):
                continue
            seen.add(src)
            image_urls.append(src)
        return image_urls

    def is_probably_reader_img(self, img):
        text = " ".join([
            " ".join(img.get("class", [])) if isinstance(img.get("class"), list) else str(img.get("class") or ""),
            str(img.get("alt") or ""),
            str(img.get("id") or ""),
        ]).lower()
        if any(x in text for x in ["page", "chapter", "reader", "reading", "manga", "webtoon"]):
            return True
        try:
            width = int(str(img.get("width") or "0").split(".")[0])
            height = int(str(img.get("height") or "0").split(".")[0])
            return width >= 300 and height >= 800 and height > width
        except Exception:
            return False

    def extract_reader_images(self, soup, page_url):
        chapter_data_images = self.extract_chapter_data_images(soup, page_url)
        if chapter_data_images:
            return chapter_data_images
        if "manhwaread.com" in urlparse(page_url).netloc.lower():
            return []

        selectors = [
            "#nkBody .pg-wrap img",
            "#readerarea img",
            ".reading-content img",
            "#imagesList img.reading-image",
            ".reading-page img",
            "img.wp-manga-chapter-img",
            ".wp-manga-chapter-img img",
            ".chapter-content img",
            ".entry-content img",
            "#chapter-reader img",
            ".chapter-reader img",
            ".reader-area img",
            ".container-chapter-reader img",
            "#_imageList img",
            ".viewer_img img",
            ".viewer_lst img",
            "img._images",
            "img[alt^='Page ']",
        ]
        image_urls = []
        seen = set()
        for selector in selectors:
            for img in soup.select(selector):
                src = self.get_image_src(img, page_url)
                if src and src not in seen:
                    seen.add(src)
                    image_urls.append(src)
        if image_urls:
            return image_urls

        for img in soup.find_all("img"):
            if not self.is_probably_reader_img(img):
                continue
            src = self.get_image_src(img, page_url)
            if src and src not in seen:
                seen.add(src)
                image_urls.append(src)
        return image_urls

    def clear_old_page_images(self, ch_folder):
        if not os.path.isdir(ch_folder):
            return
        for name in os.listdir(ch_folder):
            lower = name.lower()
            if not lower.startswith("page_"):
                continue
            if not lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                continue
            try:
                os.remove(os.path.join(ch_folder, name))
            except Exception:
                pass

    def convert_chapter_format(self, ch_folder, save_as, ch_num, save_path):
        try:
            img_files = [
                os.path.join(ch_folder, f)
                for f in sorted(os.listdir(ch_folder))
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
            ]
            if not img_files:
                return
            created = False
            if save_as in ("cbz", "zip"):
                ext = ".cbz" if save_as == "cbz" else ".zip"
                archive_path = os.path.join(save_path, f"Chapter {ch_num}{ext}")
                # Images are already compressed, ZIP_STORED is much faster with ~same size
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as zf:
                    for path in img_files:
                        zf.write(path, arcname=os.path.basename(path))
                created = True
                self.after(0, lambda e=ext: self.log(f"{e.upper()} архив үүсгэгдлээ: Chapter {ch_num}{e}"))
            elif save_as == "pdf":
                pil_imgs = []
                for f in img_files:
                    try:
                        with Image.open(f) as src_img:
                            pil_imgs.append(src_img.convert("RGB"))
                    except Exception:
                        pass
                if pil_imgs:
                    pdf_path = os.path.join(save_path, f"Chapter {ch_num}.pdf")
                    try:
                        pil_imgs[0].save(pdf_path, save_all=True, append_images=pil_imgs[1:])
                        created = True
                    finally:
                        for im in pil_imgs:
                            im.close()
                    self.after(0, lambda: self.log(f"PDF файл үүсгэгдлээ: Chapter {ch_num}.pdf"))
            if created and getattr(self, "current_delete_after", False):
                shutil.rmtree(ch_folder, ignore_errors=True)
                self.after(0, lambda: self.log(f"Chapter {ch_num}: задгай зургууд устгагдлаа."))
        except Exception as e:
            self.after(0, lambda err=str(e): self.log(f"Формат хөрвүүлэх алдаа: {err}"))

    def find_existing_page(self, ch_folder, page_num, min_bytes):
        prefix = f"page_{page_num:03d}."
        try:
            for name in os.listdir(ch_folder):
                if name.startswith(prefix) and not name.endswith(".part"):
                    path = os.path.join(ch_folder, name)
                    if os.path.getsize(path) >= min_bytes:
                        return path
        except OSError:
            pass
        return None

    def download_chapter_images(self, image_urls, ch_url, ch_folder, headers, max_workers=4, min_bytes=1000, ch_label=""):
        started_at = time.time()
        timeout = httpx.Timeout(40.0, connect=10.0)
        workers = min(max_workers, max(1, len(image_urls)))
        limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers)
        skip_existing = getattr(self, "current_skip_existing", False)
        backoff = (0.5, 1.5, 3.0)
        total = len(image_urls)

        def download_one(img_client, item):
            page_num, src = item
            if self.cancel_event.is_set():
                return None
            if skip_existing and self.find_existing_page(ch_folder, page_num, min_bytes):
                return "skipped"
            ext = src.split(".")[-1].split("?")[0].lower()
            if len(ext) > 4 or "/" in ext or not ext.isalnum():
                ext = "jpg"
            path = os.path.join(ch_folder, f"page_{page_num:03d}.{ext}")
            for attempt in range(len(backoff)):
                if self.cancel_event.is_set():
                    return None
                try:
                    img_res = img_client.get(src, headers={"Referer": ch_url, "User-Agent": headers["User-Agent"]})
                    if img_res.status_code in (403, 404, 410):
                        return False  # permanent, no point retrying
                    if img_res.status_code == 200 and len(img_res.content) >= min_bytes:
                        tmp_path = path + ".part"
                        with open(tmp_path, "wb") as f:
                            f.write(img_res.content)
                        os.replace(tmp_path, path)
                        with self._progress_lock:
                            self._bytes_downloaded += len(img_res.content)
                        return True
                    if img_res.status_code == 200:
                        return False  # too small: placeholder / ad image
                except Exception:
                    pass
                if attempt < len(backoff) - 1:
                    time.sleep(backoff[attempt])
            return False

        count = 0
        done = 0
        failed_pages = []
        with httpx.Client(cookies=self.cookies_for_url(ch_url), follow_redirects=True, timeout=timeout, limits=limits, verify=not self.should_skip_tls_verify(ch_url)) as img_client:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(download_one, img_client, item): item[0] for item in enumerate(image_urls, 1)}
                for future in as_completed(futures):
                    result = future.result()
                    done += 1
                    if result in (True, "skipped"):
                        count += 1
                    elif result is False:
                        failed_pages.append(futures[future])
                    self.report_image_progress(done, total, ch_label)
        if self.cancel_event.is_set():
            raise DownloadCancelled()
        if failed_pages:
            pages = ", ".join(str(p) for p in sorted(failed_pages)[:20])
            self.after(0, lambda p=pages, n=len(failed_pages): self.log(f"Анхаар: {n} зураг татагдсангүй (хуудас: {p})"))
        self.after(0, lambda seconds=time.time() - started_at: self.log(f"Image download time: {seconds:.1f}s"))
        return count

    def run_mytoon_scraper(self, url):
        try:
            start = self.current_start_ch
            end = self.current_end_ch
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://mytoon.site/",
            }

            self.after(0, lambda: self.log(f"MYTOON горим: {start}-аас {end} бүлэг татаж байна..."))

            # Fetch or use cached webtoon info (only if it belongs to the same webtoon)
            info = self.cached_mytoon_data
            url_id_match = re.search(r"/webtoon/(\d+)", url)
            url_webtoon_id = int(url_id_match.group(1)) if url_id_match else None
            if (not info or not info.get("all_chapters")
                    or (url_webtoon_id and info.get("webtoon_id") != url_webtoon_id)):
                info = self.extract_mytoon_data(url)
                self.cached_mytoon_data = info

            if not info:
                self.after(0, lambda: self.log("Алдаа: MyToon хуудасны өгөгдлийг уншиж чадсангүй."))
                self.after(0, lambda: messagebox.showerror("Алдаа", "MyToon мэдээлэл олдсонгүй."))
                return

            webtoon_id = info.get("webtoon_id")
            all_chapters = info.get("all_chapters", {})

            # If all_chapters is missing or incomplete, try loading webtoon main page
            if (not all_chapters or max(all_chapters.keys(), default=0) < end) and webtoon_id:
                self.after(0, lambda: self.log("Бүлгүүдийн жагсаалтыг үндсэн хуудаснаас шинэчилж байна..."))
                main_info = self.extract_mytoon_data(f"https://mytoon.site/webtoon/{webtoon_id}")
                if main_info and main_info.get("all_chapters"):
                    all_chapters.update(main_info["all_chapters"])
                    info["all_chapters"] = all_chapters
                if main_info and not info.get("title"):
                    info["title"] = main_info.get("title")

            series_folder = self.series_dir(info.get("title") or f"MyToon {webtoon_id}")
            total_chapters = end - start + 1
            self.begin_progress(total_chapters)
            downloaded_any = False

            for idx, ch_num in enumerate(range(start, end + 1)):
                self.check_cancel()
                self.set_chapter_progress(idx, f"Бүлэг {ch_num}")
                ch_entry = all_chapters.get(ch_num)
                ch_id = ch_entry.get("id") if ch_entry else None

                # If chapter ID not found directly, check by index or current chapter
                if not ch_id and info.get("current_chapter_num") == ch_num:
                    ch_id = info.get("current_chapter_id")

                if not ch_id:
                    self.after(0, lambda c=ch_num: self.log(f"Бүлэг {c}: холбогдох ID олдсонгүй."))
                    continue

                ch_url = f"https://mytoon.site/webtoon/{webtoon_id}/read/{ch_id}"
                self.after(0, lambda c=ch_num, u=ch_url: self.log(f"Холбогдож байна: Бүлэг {c} ({u})"))

                # If this chapter was already loaded during verify and has images:
                if info.get("current_chapter_id") == ch_id and info.get("current_images"):
                    image_urls = info["current_images"]
                    is_vip_blocked = info.get("is_vip_blocked", False)
                else:
                    ch_data = self.extract_mytoon_data(ch_url)
                    image_urls = ch_data.get("current_images", []) if ch_data else []
                    is_vip_blocked = ch_data.get("is_vip_blocked", False) if ch_data else False

                if is_vip_blocked or not image_urls:
                    self.after(0, lambda c=ch_num: self.log(
                        f"Бүлэг {c} түгжээтэй (VIP) байна. MYTOON НЭВТРЭХ товчоор нэвтэрнэ үү."
                    ))
                    continue

                if self.download_chapter(series_folder, ch_num, image_urls, ch_url, headers):
                    downloaded_any = True

            self.finish_download(downloaded_any, series_folder,
                                 "Зураг татагдсангүй. Бүлэг түгжээтэй эсвэл эрх дутуу байна.")
        except DownloadCancelled:
            self.after(0, lambda: self.log("Таталтыг хэрэглэгч зогсоолоо."))
        except Exception as err:
            self.after(0, lambda e=str(err): self.log(f"MyToon алдаа: {e}"))
            self.after(0, lambda e=str(err): messagebox.showerror("Системийн алдаа", e))
        finally:
            self.after(0, self.reset_ui)

    def run_manga_mn_scraper(self, url):
        try:
            start = self.current_start_ch
            end = self.current_end_ch
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://manga.mn/",
            }

            series_slug, _ = self.parse_manga_mn_url_parts(url)
            if not series_slug:
                self.after(0, lambda: self.log("Алдаа: Зөв manga.mn хаяг оруулна уу (ж.нь https://manga.mn/manga/...)."))
                self.after(0, lambda: messagebox.showerror("Алдаа", "Зөв manga.mn хаяг оруулна уу."))
                return

            self.after(0, lambda: self.log(f"MANGA.MN горим: {start}-аас {end} бүлэг татаж байна..."))

            info = self.cached_manga_mn_data
            if not info or info.get("series_slug") != series_slug or not info.get("all_chapters") or info.get("is_login_required"):
                info = self.extract_manga_mn_data(url)
                self.cached_manga_mn_data = info

            if not info:
                self.after(0, lambda: self.log("Алдаа: manga.mn хуудасны өгөгдлийг уншиж чадсангүй."))
                self.after(0, lambda: messagebox.showerror("Алдаа", "manga.mn мэдээлэл олдсонгүй."))
                return

            if info.get("is_login_required"):
                msg = "manga.mn нэвтрэлт шаардлагатай байна. Зүүн талын 'MANGA.MN LOGIN' товч дээр дарж нэвтрээд Chrome цонхоо хаасны дараа дахин оролдоно уу."
                self.after(0, lambda: self.log(msg))
                self.after(0, lambda: messagebox.showwarning("manga.mn нэвтрэх", msg))
                return

            all_chapters = info.get("all_chapters", {})
            if not all_chapters:
                series_info = self.extract_manga_mn_data(f"https://manga.mn/manga/{series_slug}")
                if series_info and series_info.get("all_chapters"):
                    all_chapters = series_info["all_chapters"]
                    info["all_chapters"] = all_chapters

            series_folder = self.series_dir(info.get("title") or series_slug)
            total_chapters = max(1, end - start + 1)
            self.begin_progress(total_chapters)
            downloaded_any = False

            with httpx.Client(headers=headers, cookies=self.cookies_for_url(url), follow_redirects=True, timeout=30.0) as client:
                for idx, ch_num in enumerate(range(start, end + 1)):
                    self.check_cancel()
                    self.set_chapter_progress(idx, f"Бүлэг {ch_num}")
                    ch_url = all_chapters.get(ch_num)
                    if not ch_url:
                        ch_url = f"https://manga.mn/manga/{series_slug}/ch{ch_num:03d}"

                    self.after(0, lambda c=ch_num, u=ch_url: self.log(f"Холбогдож байна: Бүлэг {c} ({u})"))

                    if info.get("current_chapter_url") == ch_url and info.get("current_images"):
                        image_urls = info["current_images"]
                    else:
                        res = client.get(ch_url)
                        if res.status_code != 200:
                            self.after(0, lambda c=ch_num, code=res.status_code: self.log(f"Бүлэг {c}: Хуудас олдсонгүй (HTTP {code})."))
                            continue
                        ch_soup = BeautifulSoup(res.text, "lxml")
                        if ch_soup.select_one(".nl-wrap"):
                            self.after(0, lambda c=ch_num: self.log(f"Бүлэг {c}: Нэвтрэлт шаардлагатай байна."))
                            continue
                        image_urls = self.extract_manga_mn_reader_images(ch_soup, ch_url)

                    if not image_urls:
                        self.after(0, lambda c=ch_num: self.log(f"Бүлэг {c}: Зураг олдсонгүй."))
                        continue

                    if self.download_chapter(series_folder, ch_num, image_urls, ch_url, headers):
                        downloaded_any = True

            self.finish_download(downloaded_any, series_folder,
                                 "Зураг татагдсангүй. Бүлгийн дугаар эсвэл нэвтрэлтээ шалгана уу.")
        except DownloadCancelled:
            self.after(0, lambda: self.log("Таталтыг хэрэглэгч зогсоолоо."))
        except Exception as err:
            self.after(0, lambda e=str(err): self.log(f"manga.mn алдаа: {e}"))
            self.after(0, lambda e=str(err): messagebox.showerror("Системийн алдаа", e))
        finally:
            self.after(0, self.reset_ui)

    def run_madara_scraper(self, url):
        pw_state = {}
        try:
            start = self.current_start_ch
            end = self.current_end_ch
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Referer": "https://www.google.com/",
            }
            
            # Universal Chapter Stripping: handles /chapter-1/ and /chapter/1/
            base_url = re.sub(r"chapter[/-]\d+/?$", "", url, flags=re.IGNORECASE).rstrip("/")
            base_url = re.sub(r"chapter-\d+[^/]*?/?$", "", base_url, flags=re.IGNORECASE).rstrip("-/") + "/"
            if not base_url.endswith("/") and not base_url.endswith("-"): base_url += "/"
            
            total_chapters = end - start + 1
            self.begin_progress(total_chapters)
            downloaded_any = False
            nebula_chapter_urls = {}
            series_folder = None
            self.after(0, lambda: self.log(f"Олноор татах горим: {start}-аас {end} бүлэг"))

            def ensure_series_folder(soup=None):
                """Pick the per-series output folder once, using the best title source available."""
                nonlocal series_folder
                if series_folder:
                    return series_folder
                title = None
                vs = self.verified_series
                if vs and urlparse(vs.get("url", "")).netloc == urlparse(url).netloc and vs.get("title"):
                    title = vs["title"]
                if not title and soup is not None:
                    reader = soup.select_one("#nkBody[data-manga-title]")
                    og = soup.find("meta", property="og:title")
                    if reader and reader.get("data-manga-title"):
                        title = reader["data-manga-title"]
                    elif og and og.get("content"):
                        title = self.clean_series_title(og["content"], url)
                series_folder = self.series_dir(title or self.guess_series_title(url))
                return series_folder

            with httpx.Client(headers=headers, cookies=self.cookies_for_url(url), follow_redirects=True, timeout=30.0, verify=not self.should_skip_tls_verify(url)) as client:
                if "nebula.mn" in urlparse(url).netloc.lower():
                    try:
                        index_res = client.get(url)
                        if index_res.status_code == 200:
                            index_soup = BeautifulSoup(index_res.text, "lxml")
                            nebula_chapter_urls = self.extract_nebula_chapter_urls(index_soup, url)
                            ensure_series_folder(index_soup)
                            self.after(0, lambda count=len(nebula_chapter_urls): self.log(f"Nebula: {count} бүлгийн холбоос оллоо."))
                    except Exception as err:
                        self.after(0, lambda e=str(err): self.log(f"Nebula бүлгийн жагсаалт уншиж чадсангүй: {e}"))

                for idx, ch_num in enumerate(range(start, end + 1)):
                    self.check_cancel()
                    self.set_chapter_progress(idx, f"Бүлэг {ch_num}")
                    # Try original-site pattern first, then common fallback patterns.
                    if nebula_chapter_urls:
                        mapped_url = nebula_chapter_urls.get(ch_num)
                        ch_url_patterns = [mapped_url] if mapped_url else []
                    else:
                        ch_url_patterns = self.build_chapter_url_patterns(url, base_url, ch_num)

                    if not ch_url_patterns:
                        self.after(0, lambda c=ch_num: self.log(f"Nebula: Бүлэг {c} жагсаалтад алга байна."))
                        continue
                    
                    found = False
                    locked = False
                    for ch_url in ch_url_patterns:
                        self.check_cancel()
                        self.after(0, lambda u=ch_url: self.log(f"Холбогдож байна: {u}"))
                        try:
                            res = client.get(ch_url)
                            if res.status_code == 403:
                                self.after(0, lambda: self.log("HTTP 403: сайт автомат хандалтыг хааж байна. Browser fallback руу оролдоно."))
                            if res.status_code == 200:
                                soup = BeautifulSoup(res.text, "lxml")
                                if nebula_chapter_urls:
                                    nebula_chapter_urls.update(self.extract_nebula_chapter_urls(soup, ch_url))
                                page_text = soup.get_text(" ", strip=True).lower()
                                if "nebula.mn" in urlparse(ch_url).netloc.lower() and soup.select_one("#nkLocked"):
                                    locked = True
                                    self.after(0, lambda c=ch_num: self.log(
                                        f"Nebula Бүлэг {c} түгжээтэй байна. Crown аккаунтаар дахин нэвтэрнэ үү."
                                    ))
                                    break
                                if "just a moment" in page_text or "security verification" in page_text:
                                    self.after(0, lambda: self.log("Cloudflare verification хуудас гарлаа. Browser fallback руу оролдоно."))
                                    continue
                                image_urls = self.extract_reader_images(soup, ch_url)
                                if image_urls:
                                    if "webtoons.com" in urlparse(ch_url).netloc.lower():
                                        image_urls = [u.replace("?type=q90", "") for u in image_urls]
                                    folder = ensure_series_folder(soup)
                                    if self.download_chapter(folder, ch_num, image_urls, ch_url, headers):
                                        downloaded_any = True
                                        found = True
                                        break
                        except DownloadCancelled:
                            raise
                        except Exception:
                            continue
                    
                    if not found and not locked:
                        if sync_playwright:
                            self.after(0, lambda: self.log("Playwright (Advanced) горим идэвхжлээ..."))
                            image_urls = self.run_playwright_scraper(ch_url_patterns[0], pw_state)
                            if image_urls:
                                folder = ensure_series_folder()
                                if self.download_chapter(folder, ch_num, image_urls, ch_url_patterns[0],
                                                         {"User-Agent": headers["User-Agent"]}, min_bytes=40000):
                                    downloaded_any = True
                            else:
                                self.after(0, lambda c=ch_num: self.log(f"Бүлэг {c} олдсонгүй эсвэл зураггүй байна."))
                        else:
                            self.after(0, lambda c=ch_num: self.log(f"Бүлэг {c} олдсонгүй эсвэл зураггүй байна."))

            self.finish_download(downloaded_any, series_folder,
                                 "Зураг татагдсангүй. Сайт автомат хандалтыг хааж байж болзошгүй.")
        except DownloadCancelled:
            self.after(0, lambda: self.log("Таталтыг хэрэглэгч зогсоолоо."))
        except Exception as err:
            self.after(0, lambda e=err: self.log(f"Системийн ноцтой алдаа: {str(e)}"))
        finally:
            self.close_playwright(pw_state)

    def close_playwright(self, pw_state):
        for key in ("browser", "pw"):
            obj = pw_state.pop(key, None)
            if obj is None:
                continue
            try:
                obj.close() if key == "browser" else obj.stop()
            except Exception:
                pass

    def run_playwright_scraper(self, url, pw_state):
        """Render the chapter in a (reused) headless browser and return the reader image URLs.

        The actual downloading is done by the parallel download_chapter_images pipeline.
        """
        page = None
        try:
            if "browser" not in pw_state:
                pw_state["pw"] = sync_playwright().start()
                pw_state["browser"] = self.launch_any_browser(pw_state["pw"], headless=True)
            browser = pw_state["browser"]
            page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            self.after(0, lambda: self.log(f"Browser-оор холбогдож байна: {url}"))
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            title = page.title().lower()
            body_text = page.locator("body").inner_text(timeout=5000).lower()
            if "just a moment" in title or "security verification" in body_text:
                self.after(0, lambda: self.log("Cloudflare blocked: browser дээр ч security verification дээр зогсож байна."))
                return []
            
            # Scroll to bottom to trigger all lazy loading
            page.evaluate("""
                async () => {
                    for (let y = 0; y < document.body.scrollHeight; y += 900) {
                        window.scrollTo(0, y);
                        await new Promise(resolve => setTimeout(resolve, 250));
                    }
                    window.scrollTo(0, document.body.scrollHeight);
                }
            """)
            page.wait_for_timeout(2000)
            
            # Extract image URLs with STRICT filtering (all in one JS call)
            infos = page.evaluate("""
                () => {
                    let imgs = Array.from(document.querySelectorAll('#readerarea img, .reading-content img, .wp-manga-chapter-img img'));
                    if (!imgs.length) imgs = Array.from(document.querySelectorAll('img'));
                    return imgs.map(img => ({src: img.currentSrc || img.src || img.dataset.src, w: img.naturalWidth, h: img.naturalHeight}));
                }
            """)
            image_urls = []
            for info in infos:
                src = info.get("src")
                w = info.get("w", 0) or 0
                h = info.get("h", 0) or 0
                if not src or not src.startswith("http") or src in image_urls:
                    continue
                if any(x in src.lower() for x in ["logo", "banner", "button", "icon", "promo", "ads", "discord", "social", "donate", "sub", "avatar"]):
                    continue
                if h > 0 and w > 0:
                    if h < w * 1.5: continue
                    if h < 800: continue
                    if w < 300: continue
                image_urls.append(src)
            self.after(0, lambda n=len(image_urls): self.log(f"Advanced: {n} зураг оллоо."))
            return image_urls
        except Exception as e:
            self.after(0, lambda err=str(e): self.log(f"Advanced Scraper Error: {err}"))
            return []
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

    def reset_ui(self):
        self.download_button.configure(state="normal", text="▶  ТАТАЖ ЭХЛЭХ", fg_color=self.UCHIHA_RED)
        self.cancel_button.configure(state="disabled", text="ЗОГСООХ", fg_color="#171A24", border_color="#333A4D")
        self.downloading = False
        if self.cancel_event.is_set():
            self.stats_label.configure(text="Зогсоосон")
            self.set_app_state("cancelled")
        self.refresh_session_badges()

if __name__ == "__main__":
    # When frozen by PyInstaller, use the folder of the .exe (not the temp _MEIPASS dir)
    base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    app = WebtoonDownloaderGUI()
    app.mainloop()
