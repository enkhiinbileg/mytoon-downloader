import os
import subprocess
import threading
import re
import httpx
import io
import ctypes
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

        try:
            self.current_start_ch = int(start_str) if start_str else 1
            self.current_end_ch = int(end_str) if end_str and end_str.isdigit() else self.current_start_ch
            self.current_total_chapters = self.current_end_ch - self.current_start_ch + 1
        except:
            self.current_start_ch = 1
            self.current_total_chapters = 1

        is_webtoons = "webtoons.com" in url.lower()
        
        if is_webtoons:
            args = [self.downloader_path, url]
            if start_str: args.extend(["--start", start_str])
            if end_str: args.extend(["--end", end_str])
            if save_as != "images": args.extend(["--save-as", save_as])
            if save_path: args.extend(["--out", save_path])
        else:
            args = [self.gallery_dl_path, url]
            if "manhwa" in url or "manhwa" in url:
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
            if not is_webtoons and ("manhwa" in url or "manhwa" in url):
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
            self.after(0, lambda: messagebox.showerror("Системийн алдаа", str(e)))
        finally:
            self.after(0, self.reset_ui)

    def run_madara_scraper(self, url):
        try:
            start = self.current_start_ch
            end = self.current_end_ch
            save_path = self.path_entry.get().strip() or "downloads"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            
            # Universal Chapter Stripping: handles /chapter-1/ and /chapter/1/
            base_url = re.sub(r"chapter[/-]\d+/?$", "", url, flags=re.IGNORECASE).rstrip("/")
            if not base_url.endswith("/") and not base_url.endswith("-"): base_url += "/"
            
            total_chapters = end - start + 1
            self.after(0, lambda: self.log(f"Олноор татах горим: {start}-аас {end} бүлэг"))

            with httpx.Client(headers=headers, follow_redirects=True, timeout=30.0) as client:
                for idx, ch_num in enumerate(range(start, end + 1)):
                    # Try different URL patterns
                    ch_url_patterns = [
                        f"{base_url}chapter-{ch_num}/",
                        f"{base_url}chapter/{ch_num}/",
                        f"{base_url}ch-{ch_num}/"
                    ]
                    
                    found = False
                    for ch_url in ch_url_patterns:
                        self.after(0, lambda c=ch_num: self.log(f"Холбогдож байна: {ch_url}"))
                        try:
                            res = client.get(ch_url)
                            if res.status_code == 200:
                                soup = BeautifulSoup(res.text, "lxml")
                                # Deep Scan for all images
                                all_images = soup.find_all("img")
                                self.after(0, lambda: self.log(f"Нийт {len(all_images)} зураг оллоо. Шүүж байна..."))
                                
                                if all_images:
                                    ch_folder = os.path.join(save_path, f"Chapter {ch_num}")
                                    os.makedirs(ch_folder, exist_ok=True)
                                    count = 0
                                    for img in all_images:
                                        # Exhaustive search for the real image URL
                                        possible_srcs = [
                                            img.get("data-src"), img.get("data-lazy-src"), 
                                            img.get("data-cfsrc"), img.get("data-src-optimized"),
                                            img.get("src"), img.get("srcset"), img.get("data-original-src")
                                        ]
                                        
                                        src = None
                                        for p_src in possible_srcs:
                                            if p_src:
                                                if isinstance(p_src, list): p_src = p_src[0]
                                                p_src = p_src.split(",")[0].split(" ")[0].strip()
                                                if p_src.startswith("//"): p_src = "https:" + p_src
                                                if p_src.startswith("http") and not any(x in p_src.lower() for x in ["logo", "banner", "button", "avatar", "icon"]):
                                                    src = p_src
                                                    break
                                        
                                        if not src: continue
                                        
                                        try:
                                            # Spoof referer and user-agent for each image
                                            img_res = client.get(src, headers={"Referer": ch_url})
                                            # Manga pages are usually > 20KB. Icons are small.
                                            if len(img_res.content) < 20000: continue 
                                            
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
                    
                    if not found or "asura" in url.lower():
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
