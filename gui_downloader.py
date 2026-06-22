import os
import subprocess
import threading
import re
import base64
import json
import httpx
import io
import ctypes
import time
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

class WebtoonDownloaderGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("MYTOON Pro - World Class Edition")
        self.geometry("1100x800")
        self.configure(fg_color="#050505")

        # Premium Color Palette
        self.UCHIHA_RED = "#E61919"
        self.UCHIHA_DARK_RED = "#991111"
        self.UCHIHA_BLACK = "#0A0A0A"
        self.UCHIHA_GRAY = "#151515"
        self.UCHIHA_TEXT = "#E0E0E0"

        # Downloader Paths
        self.downloader_path = r"C:\Users\Gavl\AppData\Roaming\Python\Python314\Scripts\webtoon-downloader.exe"
        self.gallery_dl_path = r"C:\Users\Gavl\AppData\Roaming\Python\Python314\Scripts\gallery-dl.exe"
        self.direct_scraper_domains = ("manhwaread.com", "manhuaus.com", "mgeko.cc", "asurascans.com", "hentai20.io", "kingofshojo.com", "nebula.mn")
        self.supported_sites_window = None
        app_data = os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
        self.nebula_session_path = os.path.join(app_data, "MYTOON-Downloader", "nebula_session.json")
        self.manga_mn_session_path = os.path.join(app_data, "MYTOON-Downloader", "manga_mn_session.json")
        
        # Grid layout (1x2)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 1. SIDEBAR - Glassmorphism Style
        self.sidebar_frame = ctk.CTkScrollableFrame(self, width=320, corner_radius=0, fg_color=self.UCHIHA_BLACK)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_frame.grid_rowconfigure(15, weight=1)

        # Logo
        try:
            if os.path.exists("logo.png"):
                logo_img_data = Image.open("logo.png")
                # Also save as ico for the window icon
                logo_img_data.save("logo.ico", format="ICO", sizes=[(32, 32), (64, 64)])
                self.after(200, lambda: self.iconbitmap("logo.ico") if os.path.exists("logo.ico") else None)
                
                logo_image = ctk.CTkImage(light_image=logo_img_data,
                                         dark_image=logo_img_data,
                                         size=(160, 96))
                self.logo_label = ctk.CTkLabel(self.sidebar_frame, image=logo_image, text="")
            else:
                self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="MYTOON", 
                                             font=ctk.CTkFont(family="Inter", size=38, weight="bold"),
                                             text_color=self.UCHIHA_RED)
        except Exception:
            self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="MYTOON", 
                                         font=ctk.CTkFont(family="Inter", size=38, weight="bold"),
                                         text_color=self.UCHIHA_RED)
            
        self.logo_label.grid(row=0, column=0, padx=20, pady=(18, 12))

        # URL Input
        self.url_label = ctk.CTkLabel(self.sidebar_frame, text="WEBTOON ХАЯГ (URL):", anchor="w", 
                                     font=ctk.CTkFont(size=12, weight="bold"), text_color=self.UCHIHA_RED)
        self.url_label.grid(row=1, column=0, padx=25, pady=(10, 0), sticky="w")
        
        self.url_entry = ctk.CTkEntry(self.sidebar_frame, placeholder_text="Хаягийг энд хуулж Enter дар...", height=40, 
                                     fg_color=self.UCHIHA_GRAY, border_color="#333333", corner_radius=10)
        self.url_entry.grid(row=2, column=0, padx=25, pady=(5, 10), sticky="ew")
        self.url_entry.bind("<Return>", lambda e: self.verify_url())

        # Info Preview Card
        self.info_card = ctk.CTkFrame(self.sidebar_frame, corner_radius=15, fg_color=self.UCHIHA_GRAY, border_width=1, border_color="#222222")
        self.info_card.grid(row=3, column=0, padx=20, pady=8, sticky="ew")
        
        self.preview_image_label = ctk.CTkLabel(self.info_card, text="Preview", width=210, height=120, 
                                               fg_color="#000000", corner_radius=10)
        self.preview_image_label.pack(padx=10, pady=(10, 5))
        
        self.webtoon_name_label = ctk.CTkLabel(self.info_card, text="Мэдээлэл байхгүй", font=ctk.CTkFont(size=14, weight="bold"), 
                                              text_color=self.UCHIHA_TEXT, wraplength=210)
        self.webtoon_name_label.pack(padx=10, pady=(5, 10))

        # Settings
        self.settings_label = ctk.CTkLabel(self.sidebar_frame, text="ТОХИРГОО", anchor="w", 
                                         font=ctk.CTkFont(size=11, weight="bold"), text_color="#555555")
        self.settings_label.grid(row=4, column=0, padx=25, pady=(20, 0), sticky="w")

        # Range
        self.range_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.range_frame.grid(row=5, column=0, padx=25, pady=5, sticky="ew")
        
        self.start_entry = ctk.CTkEntry(self.range_frame, placeholder_text="Start", width=120, height=35, corner_radius=8,
                                       fg_color=self.UCHIHA_GRAY, border_color="#333333")
        self.start_entry.insert(0, "1")
        self.start_entry.pack(side="left", padx=(0, 10))
        
        self.end_entry = ctk.CTkEntry(self.range_frame, placeholder_text="End", width=120, height=35, corner_radius=8,
                                     fg_color=self.UCHIHA_GRAY, border_color="#333333")
        self.end_entry.pack(side="left")

        # Format
        self.format_combo = ctk.CTkComboBox(self.sidebar_frame, values=["images", "pdf", "cbz", "zip"], height=35,
                                           fg_color=self.UCHIHA_GRAY, border_color="#333333", corner_radius=8,
                                           button_color=self.UCHIHA_RED, button_hover_color=self.UCHIHA_DARK_RED)
        self.format_combo.grid(row=6, column=0, padx=25, pady=10, sticky="ew")

        # Save Path
        self.path_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.path_frame.grid(row=7, column=0, padx=20, pady=8, sticky="ew")
        
        self.path_entry = ctk.CTkEntry(self.path_frame, placeholder_text="Хадгалах хавтас...", height=35, corner_radius=8,
                                      fg_color=self.UCHIHA_GRAY, border_color="#333333")
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.path_entry.insert(0, os.getcwd())

        self.browse_button = ctk.CTkButton(self.path_frame, text="Browse", width=70, height=35, corner_radius=8,
                                          command=self.browse_folder, fg_color="#222222", 
                                          hover_color="#333333", border_width=1, border_color="#444444")
        self.browse_button.pack(side="right")

        self.nebula_login_button = ctk.CTkButton(
            self.sidebar_frame, text="NEBULA НЭВТРЭХ", height=38, corner_radius=8,
            command=self.start_nebula_login, fg_color="#222222", hover_color="#333333",
            border_width=1, border_color="#6D4AFF", text_color=self.UCHIHA_TEXT
        )
        self.nebula_login_button.grid(row=8, column=0, padx=25, pady=(5, 5), sticky="ew")

        self.manga_mn_login_button = ctk.CTkButton(
            self.sidebar_frame, text="MANGA.MN LOGIN", height=38, corner_radius=8,
            command=self.start_manga_mn_login, fg_color="#222222", hover_color="#333333",
            border_width=1, border_color="#3CB371", text_color=self.UCHIHA_TEXT
        )
        self.manga_mn_login_button.grid(row=9, column=0, padx=25, pady=(5, 5), sticky="ew")

        self.supported_sites_button = ctk.CTkButton(self.sidebar_frame, text="ДЭМЖДЭГ САЙТУУД", height=38, corner_radius=8,
                                                   command=self.show_supported_sites,
                                                   fg_color="#222222", hover_color="#333333",
                                                   border_width=1, border_color=self.UCHIHA_RED,
                                                   text_color=self.UCHIHA_TEXT)
        self.supported_sites_button.grid(row=10, column=0, padx=25, pady=(5, 10), sticky="ew")

        # 2. MAIN CONTENT
        self.main_frame = ctk.CTkFrame(self, corner_radius=20, fg_color="#080808")
        self.main_frame.grid(row=0, column=1, padx=25, pady=25, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(2, weight=1)

        # Header Dashboard
        self.header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 30))
        
        self.status_title = ctk.CTkLabel(self.header_frame, text="ХЯНАХ САМБАР", font=ctk.CTkFont(size=20, weight="bold"), text_color="white")
        self.status_title.pack(side="left")

        self.download_button = ctk.CTkButton(self.header_frame, text="ТАТАЖ ЭХЛЭХ", height=50, width=200,
                                            command=self.start_download, 
                                            font=ctk.CTkFont(size=16, weight="bold"),
                                            fg_color=self.UCHIHA_RED, hover_color=self.UCHIHA_DARK_RED,
                                            corner_radius=12)
        self.download_button.pack(side="right")

        self.supported_sites_header_button = ctk.CTkButton(self.header_frame, text="ДЭМЖДЭГ САЙТУУД", height=42, width=170,
                                                           command=self.show_supported_sites,
                                                           font=ctk.CTkFont(size=13, weight="bold"),
                                                           fg_color="#222222", hover_color="#333333",
                                                           border_width=1, border_color=self.UCHIHA_RED,
                                                           corner_radius=10)
        self.supported_sites_header_button.pack(side="right", padx=(0, 12))

        # Progress Analytics
        self.analytics_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.analytics_frame.grid(row=1, column=0, sticky="ew", padx=30, pady=(0, 20))
        self.analytics_frame.grid_columnconfigure(0, weight=1)

        self.progress_bar = ctk.CTkProgressBar(self.analytics_frame, progress_color=self.UCHIHA_RED, height=18, corner_radius=10)
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 15))
        self.progress_bar.set(0)

        self.percent_label = ctk.CTkLabel(self.analytics_frame, text="0.0%", font=ctk.CTkFont(family="Consolas", size=18, weight="bold"), 
                                         text_color=self.UCHIHA_RED)
        self.percent_label.grid(row=0, column=1)

        # Terminal Log Area
        self.log_text = ctk.CTkTextbox(self.main_frame, font=ctk.CTkFont(family="Consolas", size=13),
                                      fg_color="#050505", border_width=1, border_color="#1a1a1a",
                                      text_color="#888888", corner_radius=15)
        self.log_text.grid(row=2, column=0, sticky="nsew", padx=20, pady=0)
        self.log_text.insert("0.0", "--- MYTOON Pro: Дэлхийн түвшний хувилбар ---\nСистем ажиллахад бэлэн боллоо.\n\n")
        self.log_text.configure(state="disabled")

        # Footer Actions
        self.footer_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.footer_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=15)
        
        self.clear_button = ctk.CTkButton(self.footer_frame, text="Лог цэвэрлэх", width=120, height=30, corner_radius=8,
                                         command=self.clear_logs, fg_color="#111111", 
                                         hover_color="#222222", border_width=1, border_color="#333333")
        self.clear_button.pack(side="right")

        self.downloading = False

    def log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[*] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        
        match_pct = re.search(r"(\d+)%", message)
        if match_pct:
            self.update_progress(int(match_pct.group(1)))

    def update_progress(self, percent):
        self.progress_bar.set(percent / 100)
        self.percent_label.configure(text=f"{percent}.0%")

    def clear_logs(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("0.0", "end")
        self.log_text.configure(state="disabled")
        self.update_progress(0)

    def browse_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

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
        if host == "nebula.mn" or host.endswith(".nebula.mn"):
            return self.load_nebula_cookies()
        if host == "manga.mn" or host.endswith(".manga.mn"):
            return self.load_manga_mn_cookies()
        return {}

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
                browser = playwright.chromium.launch(headless=False)
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
            self.after(0, lambda: self.nebula_login_button.configure(state="normal", text="NEBULA НЭВТРЭХ"))

    def is_manga_mn_logged_in_page(self, page):
        body_text = page.locator("body").inner_text(timeout=2000).lower()
        login_prompt = "зөвхөн бүртгэлтэй хэрэглэгчдэд" in body_text or "нэвтэрч орж уншина уу" in body_text
        auth_action = "бүртгэлээрээ нэвтрэх" in body_text or "бүртгүүлэх" in body_text
        return not login_prompt and not auth_action

    def run_manga_mn_login(self, target_url):
        browser = None
        try:
            os.makedirs(os.path.dirname(self.manga_mn_session_path), exist_ok=True)
            self.after(0, self.log, "manga.mn login browser opened. Log in manually, then wait or close the browser.")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.goto("https://manga.mn/auth/login", wait_until="domcontentloaded", timeout=60000)

                deadline = time.time() + 600
                saved = False
                left_auth_at = None
                while time.time() < deadline:
                    try:
                        if page.is_closed():
                            break
                        cookies = context.cookies("https://manga.mn")
                        on_auth_page = "/auth/login" in page.url or "/auth/register" in page.url
                        if cookies and not on_auth_page:
                            if left_auth_at is None:
                                left_auth_at = time.time()
                                page.wait_for_timeout(500)
                                continue
                            if time.time() - left_auth_at < 2:
                                page.wait_for_timeout(500)
                                continue
                            with open(self.manga_mn_session_path, "w", encoding="utf-8") as session_file:
                                json.dump(cookies, session_file, ensure_ascii=False, indent=2)
                            saved = True
                            break
                        left_auth_at = None
                        page.wait_for_timeout(500)
                    except Exception:
                        page.wait_for_timeout(500)

                if saved:
                    self.after(0, self.log, "manga.mn session saved.")
                    self.after(0, lambda: messagebox.showinfo("manga.mn", "Login session saved."))
                else:
                    self.after(0, self.log, "manga.mn login was not confirmed. Session was not saved.")

                browser.close()
        except Exception as err:
            self.after(0, self.log, f"manga.mn login error: {err}")
            self.after(0, lambda e=str(err): messagebox.showerror("manga.mn login", e))
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            self.after(0, lambda: self.manga_mn_login_button.configure(state="normal", text="MANGA.MN LOGIN"))

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
            response = httpx.get(
                target_url,
                headers={"User-Agent": "Mozilla/5.0"},
                cookies=cookie_map,
                follow_redirects=True,
                timeout=20,
            )
            if response.status_code != 200:
                return False
            soup = BeautifulSoup(response.text, "lxml")
            auth_links = [
                link.get("href", "").lower()
                for link in soup.find_all("a", href=True)
            ]
            return not any(href in ("/auth/login", "/auth/register") for href in auth_links)
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
            self.after(0, lambda: self.manga_mn_login_button.configure(state="normal", text="MANGA.MN LOGIN"))

    def normalize_input_url(self, raw_url):
        url = "".join(raw_url.split())
        if not url:
            return ""

        lower_url = url.lower()
        known_domains = list(self.direct_scraper_domains) + ["webtoons.com", "manga.mn"]

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
            if host.lower().startswith(("http://", "https://")):
                prefix = ""
            return self.restore_known_site_path(prefix + host + path)

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

        if path and not path.endswith("/") and not parsed.query and not parsed.fragment:
            path += "/"

        rebuilt = f"{parsed.scheme}://{parsed.netloc}{path}"
        if parsed.query:
            rebuilt += f"?{parsed.query}"
        if parsed.fragment:
            rebuilt += f"#{parsed.fragment}"
        return rebuilt

    def show_supported_sites(self):
        if self.supported_sites_window and self.supported_sites_window.winfo_exists():
            self.supported_sites_window.focus()
            return

        window = ctk.CTkToplevel(self)
        window.title("Дэмждэг сайтууд")
        window.geometry("720x520")
        window.configure(fg_color="#050505")
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)
        self.supported_sites_window = window

        header = ctk.CTkLabel(window, text="Зураг таталт шалгагдсан сайтууд",
                              font=ctk.CTkFont(size=22, weight="bold"),
                              text_color=self.UCHIHA_RED)
        header.grid(row=0, column=0, padx=24, pady=(22, 10), sticky="w")

        content = ctk.CTkScrollableFrame(window, fg_color="#0A0A0A", corner_radius=12)
        content.grid(row=1, column=0, padx=24, pady=(0, 18), sticky="nsew")
        content.grid_columnconfigure(0, weight=1)

        sites = [
            {
                "name": "WEBTOONS",
                "domain": "webtoons.com",
                "status": "Асуудалгүй: official Webtoons downloader ашиглана.",
                "range": "Start / End chapter range дэмжинэ.",
                "example": "https://www.webtoons.com/en/...",
            },
            {
                "name": "MANHUAUS",
                "domain": "manhuaus.com",
                "status": "Асуудалгүй шалгасан: chapter 87 дээр 63 зураг татсан.",
                "range": "chapter-20 ... chapter-40 хэлбэрийн range дэмжинэ.",
                "example": "https://manhuaus.com/manga/.../chapter-87/",
            },
            {
                "name": "Mgeko",
                "domain": "mgeko.cc",
                "status": "Асуудалгүй шалгасан: chapter 1-3 range татсан.",
                "range": "chapter-1-eng-li ... chapter-40-eng-li хэлбэрийн range дэмжинэ.",
                "example": "https://www.mgeko.cc/reader/en/...-chapter-1-eng-li/",
            },
            {
                "name": "Asura Scans",
                "domain": "asurascans.com",
                "status": "Асуудалгүй шалгасан: chapter 195 дээр 14 зураг татсан.",
                "range": "chapter/195 хэлбэрийн chapter URL дэмжинэ.",
                "example": "https://asurascans.com/comics/.../chapter/195",
            },
            {
                "name": "Hentai20",
                "domain": "hentai20.io",
                "status": "Асуудалгүй шалгасан: chapter 1 дээр 10 зураг татсан.",
                "range": "chapter-1 хэлбэрийн chapter URL дэмжинэ.",
                "example": "https://hentai20.io/...-chapter-1/",
            },
            {
                "name": "Nebula",
                "domain": "nebula.mn",
                "status": "Асуудалгүй: reader доторх бүх зургийг шууд татна.",
                "range": "Бүлгийн жагсаалтаас Start / End chapter range дэмжинэ.",
                "example": "https://nebula.mn/chapter/бүлэг-1-48/",
            },
            {
                "name": "Manga.mn",
                "domain": "manga.mn",
                "status": "Асуудалгүй: олноор татах горим дэмжигдсэн.",
                "range": "Start / End range дэмжинэ. URL pattern ашиглана.",
                "example": "https://manga.mn/manga/Teenage-mercenary/000",
            },
            {
                "name": "Universal fallback",
                "domain": "Бусад manga/manhwa сайтууд",
                "status": "Туршиж үзнэ: site бүр дээр 100% баталгаатай биш.",
                "range": "URL pattern тохирвол Start / End ажиллана.",
                "example": "Madara/reader image-тэй сайтууд",
            },
        ]

        for row, site in enumerate(sites):
            card = ctk.CTkFrame(content, fg_color="#151515", corner_radius=8,
                                border_width=1, border_color="#252525")
            card.grid(row=row, column=0, padx=12, pady=8, sticky="ew")
            card.grid_columnconfigure(0, weight=1)

            title = ctk.CTkLabel(card, text=f"{site['name']}  |  {site['domain']}",
                                 font=ctk.CTkFont(size=16, weight="bold"),
                                 text_color="white", anchor="w")
            title.grid(row=0, column=0, padx=16, pady=(12, 4), sticky="ew")

            body_text = f"{site['status']}\n{site['range']}\nЖишээ: {site['example']}"
            body = ctk.CTkLabel(card, text=body_text, justify="left", anchor="w",
                                font=ctk.CTkFont(size=13), text_color="#C8C8C8",
                                wraplength=620)
            body.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")

        close_button = ctk.CTkButton(window, text="ХААХ", width=120, height=34,
                                     command=window.destroy, fg_color=self.UCHIHA_RED,
                                     hover_color=self.UCHIHA_DARK_RED)
        close_button.grid(row=2, column=0, padx=24, pady=(0, 18), sticky="e")

    def verify_url(self):
        url = self.normalize_input_url(self.url_entry.get())
        if not url: return

        # Smart Fix for common mistakes
        if not url.startswith("http"):
            if "webtoons.com" in url: url = "https://" + url
            elif url.startswith("manhwa/") or "/viewer/" in url:
                url = "https://www.webtoons.com/en/" + url.lstrip("/")
            else:
                self.webtoon_name_label.configure(text="Хаяг буруу байна", text_color="yellow")
                return
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)

        self.webtoon_name_label.configure(text="Мэдээлэл татаж байна...", text_color="white")
        
        is_direct_preview = self.should_use_direct_scraper(url) or self.is_webtoons_viewer_url(url)

        def fetch():
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                with httpx.Client(follow_redirects=True, timeout=15.0, headers=headers, cookies=self.cookies_for_url(url), verify=not self.should_skip_tls_verify(url)) as client:
                    response = client.get(url)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, "lxml")
                        title_tag = soup.find("meta", property="og:title")
                        title = title_tag["content"] if title_tag else "Гарчиг олдсонгүй"
                        
                        # Try to find cover image
                        img_tag = soup.find("meta", property="og:image")
                        if img_tag:
                            img_url = img_tag["content"]
                            img_res = client.get(img_url)
                            img_data = Image.open(io.BytesIO(img_res.content))
                            img_data = ImageOps.fit(img_data, (250, 150), Image.Resampling.LANCZOS)
                            ctk_img = ctk.CTkImage(light_image=img_data, dark_image=img_data, size=(250, 150))
                            self.after(0, lambda: self.preview_image_label.configure(image=ctk_img, text=""))
                        
                        self.after(0, lambda: self.webtoon_name_label.configure(text=title, text_color=self.UCHIHA_RED))
                    else:
                        self.after(0, lambda: self.webtoon_name_label.configure(text=f"Алдаа {response.status_code}", text_color="yellow"))
            except Exception as e:
                self.after(0, lambda: self.webtoon_name_label.configure(text="Холболтын алдаа", text_color="yellow"))

        threading.Thread(target=fetch, daemon=True).start()

    def start_download(self):
        if self.downloading: return
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
        save_path = self.path_entry.get().strip()

        chapter_from_url = self.extract_chapter_number(url)

        try:
            if chapter_from_url and (not start_str or start_str == "1") and not end_str:
                self.current_start_ch = chapter_from_url
            else:
                self.current_start_ch = int(start_str) if start_str else (chapter_from_url or 1)
            self.current_end_ch = int(end_str) if end_str and end_str.isdigit() else self.current_start_ch
            self.current_total_chapters = self.current_end_ch - self.current_start_ch + 1
        except:
            self.current_start_ch = chapter_from_url or 1
            self.current_end_ch = self.current_start_ch
            self.current_total_chapters = 1

        if url != self.url_entry.get().strip():
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)

        is_webtoons = "webtoons.com" in url.lower()
        is_webtoons_viewer = self.is_webtoons_viewer_url(url)
        is_manga_mn = "manga.mn" in urlparse(url).netloc.lower()
        is_manhwaread = "manhwaread.com" in urlparse(url).netloc.lower()
        is_direct_scraper = is_manhwaread or is_manga_mn or self.should_use_direct_scraper(url)

        if is_webtoons and not is_webtoons_viewer:
            engine_name = "WEBTOONS"
            args = [self.downloader_path, url]
            if start_str: args.extend(["--start", start_str])
            if end_str: args.extend(["--end", end_str])
            if save_as != "images": args.extend(["--save-as", save_as])
            if save_path: args.extend(["--out", save_path])
        elif is_direct_scraper or is_webtoons_viewer:
            engine_name = "Direct scraper"
            args = ["direct-scraper", url]
        else:
            engine_name = "gallery-dl"
            args = [self.gallery_dl_path, url]
            if "manhwa" in url.lower() or "manhua" in url.lower():
                args.extend(["-o", "extractor.madara.domain=" + url.split("/")[2]])
            if start_str or end_str:
                args.extend(["--range", f"{start_str if start_str else ''}-{end_str if end_str else ''}"])
            if save_path: args.extend(["--directory", save_path])

        self.download_button.configure(state="disabled", text="ТАТАЖ БАЙНА...", fg_color="#333333")
        self.update_progress(0)
        self.downloading = True
        self.log(f"Эхлүүлж байна: {url}")
        
        self.log(f"Engine: {engine_name}")

        threading.Thread(target=self.run_downloader, args=(args,), daemon=True).start()

    def run_downloader(self, args):
        url = args[1]
        is_webtoons = "webtoons.com" in url.lower()
        try:
            if args[0] == "direct-scraper" or (not is_webtoons and self.should_use_direct_scraper(url)):
                self.run_madara_scraper(url)
                return

            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, bufsize=1)
            for line in process.stdout:
                clean = line.strip().replace('\r', '\n')
                for sl in clean.split('\n'):
                    if sl: self.after(0, self.log, sl)
            process.wait()
            if process.returncode == 0:
                self.after(0, lambda: self.update_progress(100))
                self.after(0, lambda: messagebox.showinfo("Амжилттай", "Татах ажиллагаа дууслаа!"))
            else:
                self.after(0, lambda: self.log("Үндсэн систем амжилтгүй. Нөөц системээр оролдож байна..."))
                self.run_madara_scraper(url)
        except Exception as e:
            if not is_webtoons:
                self.after(0, lambda err=str(e): self.log(f"Universal fallback: {err}"))
                self.run_madara_scraper(url)
            else:
                self.after(0, lambda: messagebox.showerror("Системийн алдаа", str(e)))
        finally:
            self.after(0, self.reset_ui)

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
        match = re.search(r"(?:/|-)chapter[/-](\d+)(?:[/?#-]|$)", url, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        decoded_url = unquote(url)
        match = re.search(r"/chapter/бүлэг-(\d+)(?:-[^/?#]+)?/?$", decoded_url, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"[?&]episode_no=(\d+)(?:&|$)", url, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        if "manga.mn/manga/" in url.lower():
            match = re.search(r"manga\.mn/manga/[^/]+/(\d+)", url, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

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
        if "manga.mn/manga/" in url.lower():
            manga_match = re.search(r"(?i)(manga\.mn/manga/[^/]+/)\d*", url)
            if manga_match:
                prefix = manga_match.group(1)
                patterns.append(f"https://{prefix}{str(ch_num).zfill(3)}")
                patterns.append(f"https://{prefix}{str(ch_num)}")
                patterns.append(f"http://{prefix}{str(ch_num).zfill(3)}")
                patterns.append(f"http://{prefix}{str(ch_num)}")
        
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

    def download_chapter_images(self, image_urls, ch_url, ch_folder, headers, max_workers=4):
        started_at = time.time()
        timeout = httpx.Timeout(20.0, connect=10.0)
        workers = min(max_workers, max(1, len(image_urls)))
        limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers)

        def download_one(img_client, item):
            page_num, src = item
            try:
                ext = src.split(".")[-1].split("?")[0]
                if len(ext) > 4 or "/" in ext:
                    ext = "jpg"
                path = os.path.join(ch_folder, f"page_{page_num:03d}.{ext}")
                img_res = img_client.get(src, headers={"Referer": ch_url, "User-Agent": headers["User-Agent"]})
                if img_res.status_code != 200 or len(img_res.content) < 1000:
                    return False
                with open(path, "wb") as f:
                    f.write(img_res.content)
                return True
            except Exception:
                return False

        count = 0
        with httpx.Client(cookies=self.cookies_for_url(ch_url), follow_redirects=True, timeout=timeout, limits=limits, verify=not self.should_skip_tls_verify(ch_url)) as img_client:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(download_one, img_client, item) for item in enumerate(image_urls, 1)]
                for future in as_completed(futures):
                    if future.result():
                        count += 1
                        self.after(0, lambda c=count, total=len(image_urls): self.log(f"Image {c}/{total} downloaded"))
        self.after(0, lambda seconds=time.time() - started_at: self.log(f"Image download time: {seconds:.1f}s"))
        return count

    def run_madara_scraper(self, url):
        try:
            start = self.current_start_ch
            end = self.current_end_ch
            save_path = self.path_entry.get().strip() or "downloads"
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
            downloaded_any = False
            nebula_chapter_urls = {}
            self.after(0, lambda: self.log(f"Олноор татах горим: {start}-аас {end} бүлэг"))

            with httpx.Client(headers=headers, cookies=self.cookies_for_url(url), follow_redirects=True, timeout=30.0, verify=not self.should_skip_tls_verify(url)) as client:
                if "nebula.mn" in urlparse(url).netloc.lower():
                    try:
                        index_res = client.get(url)
                        if index_res.status_code == 200:
                            index_soup = BeautifulSoup(index_res.text, "lxml")
                            nebula_chapter_urls = self.extract_nebula_chapter_urls(index_soup, url)
                            self.after(0, lambda count=len(nebula_chapter_urls): self.log(f"Nebula: {count} бүлгийн холбоос оллоо."))
                    except Exception as err:
                        self.after(0, lambda e=str(err): self.log(f"Nebula бүлгийн жагсаалт уншиж чадсангүй: {e}"))

                for idx, ch_num in enumerate(range(start, end + 1)):
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
                        self.after(0, lambda c=ch_num: self.log(f"Холбогдож байна: {ch_url}"))
                        try:
                            res = client.get(ch_url)
                            if res.status_code == 403:
                                self.after(0, lambda: self.log("HTTP 403: site automated access-iig haaj baina. Browser fallback ruu oroldono."))
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
                                    self.after(0, lambda: self.log("Cloudflare verification page ilersen. Browser fallback ruu oroldono."))
                                    continue
                                image_urls = self.extract_reader_images(soup, ch_url)
                                self.after(0, lambda count=len(image_urls): self.log(f"Нийт {count} зураг оллоо. Татаж байна..."))
                                
                                if image_urls:
                                    ch_folder = os.path.join(save_path, f"Chapter {ch_num}")
                                    os.makedirs(ch_folder, exist_ok=True)
                                    self.clear_old_page_images(ch_folder)
                                    count = self.download_chapter_images(image_urls, ch_url, ch_folder, headers)
                                    
                                    if count > 0:
                                        downloaded_any = True
                                        self.after(0, lambda c=ch_num, cnt=count: self.log(f"Бүлэг {c} амжилттай: {cnt} зураг татлаа."))
                                        self.after(0, lambda p=int(((idx + 1) / total_chapters) * 100): self.update_progress(p))
                                        found = True
                                        break
                        except: continue
                    
                    if not found and not locked:
                        if sync_playwright:
                            self.after(0, lambda: self.log("Playwright (Advanced) горим идэвхжлээ..."))
                            found = self.run_playwright_scraper(ch_url_patterns[0], ch_num, save_path)
                        else:
                            self.after(0, lambda c=ch_num: self.log(f"Бүлэг {c} олдсонгүй эсвэл зураггүй байна."))
                
                if downloaded_any:
                    self.after(0, lambda: messagebox.showinfo("Done", "Download finished."))
                else:
                    self.after(0, lambda: self.log("No images downloaded. Site may be blocking automated access."))
                    self.after(0, lambda: messagebox.showwarning("Blocked", "No images downloaded. Site may be blocking automated access."))
        except Exception as err:
            self.after(0, lambda e=err: self.log(f"Системийн ноцтой алдаа: {str(e)}"))

    def run_playwright_scraper(self, url, ch_num, save_path):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                
                # INJECT COOKIES
                cookies_dict = self.cookies_for_url(url)
                if cookies_dict:
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc
                    playwright_cookies = []
                    for name, value in cookies_dict.items():
                        playwright_cookies.append({
                            "name": name,
                            "value": value,
                            "domain": domain,
                            "path": "/"
                        })
                    context.add_cookies(playwright_cookies)
                
                page = context.new_page()
                
                self.after(0, lambda: self.log(f"Browser-оор холбогдож байна: {url}"))
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                title = page.title().lower()
                body_text = page.locator("body").inner_text(timeout=5000).lower()
                if "just a moment" in title or "security verification" in body_text:
                    self.after(0, lambda: self.log("Cloudflare blocked: browser deer ch security verification deer zogsoj baina."))
                    browser.close()
                    return False
                
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
                page.wait_for_timeout(2000) # Wait for images to load
                
                # Extract image URLs with STRICT filtering
                # Only target the main reader area to avoid ads
                image_elements = page.query_selector_all("#readerarea img, .reading-content img, .wp-manga-chapter-img img")
                
                if not image_elements:
                    # Very last resort, but still with strict filters
                    image_elements = page.query_selector_all("img")

                ch_folder = os.path.join(save_path, f"Chapter {ch_num}")
                os.makedirs(ch_folder, exist_ok=True)
                self.clear_old_page_images(ch_folder)
                
                count = 0
                for img in image_elements:
                    try:
                        # Get dimensions and src using JS for accuracy
                        info = page.evaluate("(img) => ({src: img.getAttribute('data-src') || img.dataset?.src || img.src, w: img.naturalWidth, h: img.naturalHeight})", img)
                        src = info.get("src")
                        w = info.get("w", 0)
                        h = info.get("h", 0)
                        
                        if not src or not src.startswith("http"): continue
                        
                        self.after(0, lambda s=src: self.log(f"Playwright found img: {s}"))
                        
                        if not src or not src.startswith("http"): continue
                        
                        # ULTRA STRICT FILTERS:
                        # 1. Exclusion keywords
                        if any(x in src.lower() for x in ["logo", "banner", "button", "icon", "promo", "ads", "discord", "social", "donate", "sub", "avatar"]):
                            continue
                        
                        # 2. Size: Loosened to support manga.mn split pages
                        if h > 0 and w > 0:
                            if h < 200: continue # Skip very small elements
                            if w < 200: continue # Skip very thin elements
                        
                        # Download using playwright context request to bypass Cloudflare
                        self.after(0, lambda s=src: self.log(f"Downloading {s}"))
                        img_res = context.request.get(src, timeout=20000)
                        img_bytes = img_res.body()
                        self.after(0, lambda s=len(img_bytes): self.log(f"Downloaded {s} bytes"))
                        if len(img_bytes) < 10000: continue # Pages should be > 10KB
                        
                        ext = src.split(".")[-1].split("?")[0]
                        if len(ext) > 4: ext = "jpg"
                        with open(os.path.join(ch_folder, f"page_{count+1:03d}.{ext}"), "wb") as f:
                            f.write(img_bytes)
                        count += 1
                    except Exception as ex:
                        self.after(0, lambda err=str(ex): self.log(f"Playwright download error: {err}"))
                        continue
                
                browser.close()
                if count > 0:
                    self.after(0, lambda c=ch_num, cnt=count: self.log(f"Бүлэг {c} амжилттай (Advanced): {cnt} зураг татлаа."))
                    return True
            return False
        except Exception as e:
            self.after(0, lambda err=str(e): self.log(f"Advanced Scraper Error: {err}"))
            return False

    def reset_ui(self):
        self.download_button.configure(state="normal", text="ТАТАЖ ЭХЛЭХ", fg_color=self.UCHIHA_RED)
        self.downloading = False

    def verify_url(self):
        url = self.normalize_input_url(self.url_entry.get())
        if not url:
            return

        # Smart Fix: Only prepend webtoons.com if it's a known webtoons path
        if not url.startswith("http"):
            if "webtoons.com" in url:
                url = "https://" + url
            elif url.startswith("manhwa/") or "/viewer/" in url:
                url = "https://www.webtoons.com/en/" + url.lstrip("/")
            else:
                self.webtoon_name_label.configure(text="Анхаар: Бүтэн URL оруулна уу (https://...)", text_color="yellow")
                return
            
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)

        is_webtoons = "webtoons.com" in url.lower()
        self.webtoon_name_label.configure(text="Холбогдож байна...", text_color="white")
        
        def fetch():
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://www.google.com/",
                }
                with httpx.Client(follow_redirects=True, timeout=10.0, headers=headers, cookies=self.cookies_for_url(url), verify=not self.should_skip_tls_verify(url)) as client:
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

                        if "nebula.mn" in urlparse(url).netloc.lower():
                            locked = soup.select_one("#nkLocked") is not None
                            image_count = len(self.extract_reader_images(soup, url))
                            access = "Crown session шаардлагатай" if locked else f"{image_count} зураг"
                            title = f"{title}\n{access}"
                        self.after(0, lambda t=title: self.webtoon_name_label.configure(text=f"Олдлоо: {t}", text_color=self.UCHIHA_RED))
                    else:
                        if self.should_use_direct_scraper(url) or self.is_webtoons_viewer_url(url):
                            self.after(0, lambda: self.webtoon_name_label.configure(text="Direct scraper gorimoor tatah bolomjtoi", text_color="cyan"))
                        elif not is_webtoons:
                            # For other sites, verification might fail but gallery-dl might still work
                            self.after(0, lambda: self.webtoon_name_label.configure(text="Universal горимоор татах боломжтой", text_color="cyan"))
                        else:
                            self.after(0, lambda: self.webtoon_name_label.configure(text=f"Алдаа: {response.status_code}", text_color="yellow"))
            except Exception:
                if self.should_use_direct_scraper(url) or self.is_webtoons_viewer_url(url):
                    self.after(0, lambda: self.webtoon_name_label.configure(text="Direct scraper gorimoor tataj uzne", text_color="cyan"))
                elif not is_webtoons:
                    self.after(0, lambda: self.webtoon_name_label.configure(text="Universal горимоор татаж үзнэ үү", text_color="cyan"))
                else:
                    self.after(0, lambda: self.webtoon_name_label.configure(text="Алдаа: Хаяг буруу", text_color="yellow"))

        threading.Thread(target=fetch, daemon=True).start()

if __name__ == "__main__":
    app = WebtoonDownloaderGUI()
    app.mainloop()
