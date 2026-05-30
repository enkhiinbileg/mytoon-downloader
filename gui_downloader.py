import os
import subprocess
import threading
import re
import httpx
import io
import ctypes
from urllib.parse import urljoin, urlparse
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
        self.direct_scraper_domains = ("manhuaus.com", "mgeko.cc", "asurascans.com", "hentai20.io")
        self.supported_sites_window = None
        
        # Grid layout (1x2)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 1. SIDEBAR - Glassmorphism Style
        self.sidebar_frame = ctk.CTkFrame(self, width=320, corner_radius=0, fg_color=self.UCHIHA_BLACK)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
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
                                         size=(200, 120))
                self.logo_label = ctk.CTkLabel(self.sidebar_frame, image=logo_image, text="")
            else:
                self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="MYTOON", 
                                             font=ctk.CTkFont(family="Inter", size=38, weight="bold"),
                                             text_color=self.UCHIHA_RED)
        except Exception:
            self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="MYTOON", 
                                         font=ctk.CTkFont(family="Inter", size=38, weight="bold"),
                                         text_color=self.UCHIHA_RED)
            
        self.logo_label.grid(row=0, column=0, padx=20, pady=(30, 20))

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
        self.info_card.grid(row=3, column=0, padx=25, pady=10, sticky="ew")
        
        self.preview_image_label = ctk.CTkLabel(self.info_card, text="Preview", width=250, height=150, 
                                               fg_color="#000000", corner_radius=10)
        self.preview_image_label.pack(padx=10, pady=(10, 5))
        
        self.webtoon_name_label = ctk.CTkLabel(self.info_card, text="Мэдээлэл байхгүй", font=ctk.CTkFont(size=14, weight="bold"), 
                                              text_color=self.UCHIHA_TEXT, wraplength=230)
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
        self.path_frame.grid(row=7, column=0, padx=25, pady=10, sticky="ew")
        
        self.path_entry = ctk.CTkEntry(self.path_frame, placeholder_text="Хадгалах хавтас...", height=35, corner_radius=8,
                                      fg_color=self.UCHIHA_GRAY, border_color="#333333")
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.path_entry.insert(0, os.getcwd())

        self.browse_button = ctk.CTkButton(self.path_frame, text="Browse", width=70, height=35, corner_radius=8,
                                          command=self.browse_folder, fg_color="#222222", 
                                          hover_color="#333333", border_width=1, border_color="#444444")
        self.browse_button.pack(side="right")

        self.supported_sites_button = ctk.CTkButton(self.sidebar_frame, text="ДЭМЖДЭГ САЙТУУД", height=38, corner_radius=8,
                                                   command=self.show_supported_sites,
                                                   fg_color="#222222", hover_color="#333333",
                                                   border_width=1, border_color=self.UCHIHA_RED,
                                                   text_color=self.UCHIHA_TEXT)
        self.supported_sites_button.grid(row=8, column=0, padx=25, pady=(5, 10), sticky="ew")

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
        url = "".join(self.url_entry.get().split())
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
        
        def fetch():
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                with httpx.Client(follow_redirects=True, timeout=15.0, headers=headers) as client:
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
        url = "".join(self.url_entry.get().split())
        if not url:
            messagebox.showerror("Алдаа", "URL хаяг оруулна уу")
            return

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

        is_webtoons = "webtoons.com" in url.lower()
        is_webtoons_viewer = self.is_webtoons_viewer_url(url)
        is_direct_scraper = self.should_use_direct_scraper(url)
        
        if is_webtoons and not is_webtoons_viewer:
            args = [self.downloader_path, url]
            if start_str: args.extend(["--start", start_str])
            if end_str: args.extend(["--end", end_str])
            if save_as != "images": args.extend(["--save-as", save_as])
            if save_path: args.extend(["--out", save_path])
        elif is_direct_scraper or is_webtoons_viewer:
            args = ["direct-scraper", url]
        else:
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

    def is_webtoons_viewer_url(self, url):
        parsed = urlparse(url)
        return "webtoons.com" in parsed.netloc.lower() and ("/viewer" in parsed.path.lower() or "episode_no=" in parsed.query.lower())

    def extract_chapter_number(self, url):
        match = re.search(r"(?:/|-)chapter[/-](\d+)(?:[/?#-]|$)", url, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        match = re.search(r"[?&]episode_no=(\d+)(?:&|$)", url, flags=re.IGNORECASE)
        return int(match.group(1)) if match else None

    def build_chapter_url_patterns(self, url, base_url, ch_num):
        patterns = []
        if self.extract_chapter_number(url):
            replaced_url = re.sub(
                r"(?i)(chapter[/-])\d+",
                lambda match: f"{match.group(1)}{ch_num}",
                url,
                count=1,
            )
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

    def extract_reader_images(self, soup, page_url):
        selectors = [
            "#readerarea img",
            ".reading-content img",
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
            src = self.get_image_src(img, page_url)
            if src and src not in seen:
                seen.add(src)
                image_urls.append(src)
        return image_urls

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
            self.after(0, lambda: self.log(f"Олноор татах горим: {start}-аас {end} бүлэг"))

            with httpx.Client(headers=headers, follow_redirects=True, timeout=30.0) as client:
                for idx, ch_num in enumerate(range(start, end + 1)):
                    # Try original-site pattern first, then common fallback patterns.
                    ch_url_patterns = self.build_chapter_url_patterns(url, base_url, ch_num)
                    
                    found = False
                    for ch_url in ch_url_patterns:
                        self.after(0, lambda c=ch_num: self.log(f"Холбогдож байна: {ch_url}"))
                        try:
                            res = client.get(ch_url)
                            if res.status_code == 200:
                                soup = BeautifulSoup(res.text, "lxml")
                                image_urls = self.extract_reader_images(soup, ch_url)
                                self.after(0, lambda count=len(image_urls): self.log(f"Нийт {count} зураг оллоо. Татаж байна..."))
                                
                                if image_urls:
                                    ch_folder = os.path.join(save_path, f"Chapter {ch_num}")
                                    os.makedirs(ch_folder, exist_ok=True)
                                    count = 0
                                    for src in image_urls:
                                        try:
                                            # Spoof referer and user-agent for each image
                                            img_res = client.get(src, headers={"Referer": ch_url, "User-Agent": headers["User-Agent"]})
                                            if img_res.status_code != 200:
                                                continue
                                            # Reader selectors already filter the page; keep small panels/credits too.
                                            if len(img_res.content) < 1000: continue 
                                            
                                            ext = src.split(".")[-1].split("?")[0]
                                            if len(ext) > 4 or "/" in ext: ext = "jpg"
                                            with open(os.path.join(ch_folder, f"page_{count+1:03d}.{ext}"), "wb") as f:
                                                f.write(img_res.content)
                                            count += 1
                                        except: continue
                                    
                                    if count > 0:
                                        self.after(0, lambda c=ch_num, cnt=count: self.log(f"Бүлэг {c} амжилттай: {cnt} зураг татлаа."))
                                        self.after(0, lambda p=int(((idx + 1) / total_chapters) * 100): self.update_progress(p))
                                        found = True
                                        break
                        except: continue
                    
                    if not found:
                        if sync_playwright:
                            self.after(0, lambda: self.log("Playwright (Advanced) горим идэвхжлээ..."))
                            found = self.run_playwright_scraper(ch_url, ch_num, save_path)
                        else:
                            self.after(0, lambda c=ch_num: self.log(f"Бүлэг {c} олдсонгүй эсвэл зураггүй байна."))
                
                self.after(0, lambda: messagebox.showinfo("Амжилттай", "Бүх бүлгийг амжилттай татаж дууслаа!"))
        except Exception as err:
            self.after(0, lambda e=err: self.log(f"Системийн ноцтой алдаа: {str(e)}"))

    def run_playwright_scraper(self, url, ch_num, save_path):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                
                self.after(0, lambda: self.log(f"Browser-оор холбогдож байна: {url}"))
                page.goto(url, wait_until="networkidle", timeout=60000)
                
                # Scroll to bottom to trigger all lazy loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000) # Wait for images to load
                
                # Extract image URLs with STRICT filtering
                # Only target the main reader area to avoid ads
                image_elements = page.query_selector_all("#readerarea img, .reading-content img, .wp-manga-chapter-img img")
                
                if not image_elements:
                    # Very last resort, but still with strict filters
                    image_elements = page.query_selector_all("img")

                ch_folder = os.path.join(save_path, f"Chapter {ch_num}")
                os.makedirs(ch_folder, exist_ok=True)
                
                count = 0
                for img in image_elements:
                    try:
                        # Get dimensions and src using JS for accuracy
                        info = page.evaluate("(img) => ({src: img.src || img.dataset.src, w: img.naturalWidth, h: img.naturalHeight})", img)
                        src = info.get("src")
                        w = info.get("w", 0)
                        h = info.get("h", 0)
                        
                        if not src or not src.startswith("http"): continue
                        
                        # ULTRA STRICT FILTERS:
                        # 1. Exclusion keywords
                        if any(x in src.lower() for x in ["logo", "banner", "button", "icon", "promo", "ads", "discord", "social", "donate", "sub", "avatar"]):
                            continue
                        
                        # 2. Aspect Ratio & Size: 
                        # Real manga pages are VERY TALL (h > w * 1.5) and high res (h > 800)
                        if h > 0 and w > 0:
                            if h < w * 1.5: continue # Skip square/landscape (h must be 1.5x width)
                            if h < 800: continue # Skip small elements
                            if w < 300: continue # Skip tiny vertical lines
                        
                        # Download using httpx
                        headers = {"User-Agent": "Mozilla/5.0", "Referer": url}
                        with httpx.Client(headers=headers, follow_redirects=True, timeout=20.0) as client:
                            img_res = client.get(src)
                            if len(img_res.content) < 40000: continue # Manga pages are usually > 40KB
                            
                            ext = src.split(".")[-1].split("?")[0]
                            if len(ext) > 4: ext = "jpg"
                            with open(os.path.join(ch_folder, f"page_{count+1:03d}.{ext}"), "wb") as f:
                                f.write(img_res.content)
                            count += 1
                    except: continue
                
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
        url = self.url_entry.get().strip()
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
                with httpx.Client(follow_redirects=True, timeout=10.0, headers=headers) as client:
                    response = client.get(url)
                    
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, "lxml")
                        title_tag = soup.find("meta", property="og:title")
                        title = title_tag["content"] if title_tag else "Мэдээлэл олдсонгүй"
                        self.after(0, lambda: self.webtoon_name_label.configure(text=f"Олдлоо: {title}", text_color=self.UCHIHA_RED))
                    else:
                        if not is_webtoons:
                            # For other sites, verification might fail but gallery-dl might still work
                            self.after(0, lambda: self.webtoon_name_label.configure(text="Universal горимоор татах боломжтой", text_color="cyan"))
                        else:
                            self.after(0, lambda: self.webtoon_name_label.configure(text=f"Алдаа: {response.status_code}", text_color="yellow"))
            except Exception:
                if not is_webtoons:
                    self.after(0, lambda: self.webtoon_name_label.configure(text="Universal горимоор татаж үзнэ үү", text_color="cyan"))
                else:
                    self.after(0, lambda: self.webtoon_name_label.configure(text="Алдаа: Хаяг буруу", text_color="yellow"))

        threading.Thread(target=fetch, daemon=True).start()

if __name__ == "__main__":
    app = WebtoonDownloaderGUI()
    app.mainloop()
