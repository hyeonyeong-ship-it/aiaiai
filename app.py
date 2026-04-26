import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import threading
import json
import os
import requests
import webbrowser
import random
from io import BytesIO

try:
    import google.generativeai as genai
except ImportError:
    pass

try:
    from PIL import Image, ImageTk
except ImportError:
    pass

CONFIG_FILE = "config.json"

def load_keys():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("gemini_api_key", data.get("api_key", "")), data.get("kakao_api_key", "")
        except:
            pass
    return "", ""

def save_keys(gemini, kakao):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"gemini_api_key": gemini, "kakao_api_key": kakao}, f)
    except:
        pass

_cached_model_name = None

# 1. Gemini로 최적의 검색어 추출
def get_search_keyword(api_key, location, food):
    global _cached_model_name
    try:
        genai.configure(api_key=api_key)
        
        # 모델 이름을 한 번만 불러와서 저장해둠 (할당량 초과 방지)
        if not _cached_model_name:
            available_models = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
            if not available_models:
                raise Exception("API 키로 접근할 수 있는 모델이 없습니다.")
                
            target_model = available_models[0]
            for m in available_models:
                if '2.5-flash' in m:
                    target_model = m
                    break
                elif '1.5-flash' in m:
                    target_model = m
                    break
            _cached_model_name = target_model
            
        model = genai.GenerativeModel(_cached_model_name)
        
        prompt = f"""
사용자가 카카오맵에서 맛집을 검색하려고 합니다.
지역: {location}
조건: {food if food else '유명한 맛집'}

카카오맵 검색창에 입력할 가장 완벽하고 간결한 검색어 딱 1개만 말해주세요.
(예시: "서울 강남구 돈까스 맛집", "부산 서면 국밥 맛집", "제주시 흑돼지")
다른 부연 설명 없이 검색어만 출력하세요.
"""
        try:
            response = model.generate_content(prompt)
            return response.text.strip().replace('"', '').replace("'", "")
        except Exception as e:
            error_msg = str(e)
            if '429' in error_msg or 'quota' in error_msg.lower():
                raise Exception("구글 Gemini 무료 사용량(1분당/하루 요청 횟수)을 초과했습니다.\n잠시 후 다시 시도해주세요!")
            else:
                raise e
    except Exception as e:
        raise Exception(f"Gemini API 오류: {str(e)}")

# 2. Kakao 로컬 API로 실제 식당 검색
def search_kakao_places(api_key, keyword):
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    # category_group_code=FD6 (음식점)
    params = {"query": keyword, "category_group_code": "FD6", "size": 15}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code != 200:
        raise Exception(f"카카오 로컬 API 오류: {response.text}")
        
    data = response.json()
    return data.get('documents', [])

# 3. Kakao 이미지 API로 식당 사진 검색
def search_kakao_image(api_key, place_name):
    url = "https://dapi.kakao.com/v2/search/image"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"query": place_name, "size": 1}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()
        docs = data.get('documents', [])
        if docs:
            return docs[0].get('image_url')
    return None

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        self.window_id = canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 캔버스 너비에 맞게 프레임 너비 동기화
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(self.window_id, width=e.width))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Mac, Windows, Linux 마우스 스크롤 통합 지원
        def _on_mousewheel(event):
            if event.delta: # Windows & Mac
                direction = -1 if event.delta > 0 else 1
                canvas.yview_scroll(direction, "units")
            else: # Linux
                direction = -1 if getattr(event, 'num', 0) == 4 else 1
                canvas.yview_scroll(direction, "units")
                
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("찐 맛집 사진/주소 추천 앱 (v3.0)")
        self.root.geometry("650x800")
        self.root.configure(padx=15, pady=15)
        
        # 단축키 설정 (Mac은 Command, Windows는 기본적으로 Control 키가 내장 지원됨)
        self.root.bind('<Command-v>', lambda e: self.root.focus_get().event_generate('<<Paste>>'))
        self.root.bind('<Command-c>', lambda e: self.root.focus_get().event_generate('<<Copy>>'))
        self.root.bind('<Command-x>', lambda e: self.root.focus_get().event_generate('<<Cut>>'))
        
        # 제목 프레임
        title_frame = tk.Frame(root)
        title_frame.pack(fill='x', pady=(0, 15))
        
        tk.Label(title_frame, text="🚀 지역별 맛집 찾기", font=("Helvetica", 18, "bold")).pack(side='left')
        tk.Label(title_frame, text="(꼭 지역명으로 입력해주세요!)", font=("Helvetica", 11), fg="gray").pack(side='left', padx=(5, 0), pady=(5,0))
        
        def toggle_api():
            if self.frame_api.winfo_ismapped():
                self.frame_api.pack_forget()
            else:
                self.frame_api.pack(fill='x', pady=5, after=title_frame)
                
        tk.Button(title_frame, text="⚙️ API 설정", command=toggle_api).pack(side='right')
        
        # API 설정 프레임
        self.frame_api = tk.LabelFrame(root, text="API 키 설정 (필수)", padx=10, pady=10)
        self.frame_api.pack(fill='x', pady=5)
        
        tk.Label(self.frame_api, text="Gemini API 키:", font=("Helvetica", 10)).grid(row=0, column=0, sticky='e', pady=2)
        self.entry_gemini = tk.Entry(self.frame_api, width=40)
        self.entry_gemini.grid(row=0, column=1, padx=5, pady=2)
        
        tk.Label(self.frame_api, text="Kakao REST API 키:", font=("Helvetica", 10)).grid(row=1, column=0, sticky='e', pady=2)
        self.entry_kakao = tk.Entry(self.frame_api, width=40)
        self.entry_kakao.grid(row=1, column=1, padx=5, pady=2)
        
        def paste_gemini():
            try:
                self.entry_gemini.delete(0, tk.END)
                self.entry_gemini.insert(0, self.root.clipboard_get())
            except: pass
            
        def paste_kakao():
            try:
                self.entry_kakao.delete(0, tk.END)
                self.entry_kakao.insert(0, self.root.clipboard_get())
            except: pass
            
        tk.Button(self.frame_api, text="붙여넣기", command=paste_gemini).grid(row=0, column=2, padx=2)
        tk.Button(self.frame_api, text="붙여넣기", command=paste_kakao).grid(row=1, column=2, padx=2)
        
        btn_save = tk.Button(self.frame_api, text="저장", command=self.on_save_keys)
        btn_save.grid(row=0, column=3, rowspan=2, padx=10)
        
        # 키 불러오기
        gemini_k, kakao_k = load_keys()
        self.entry_gemini.insert(0, gemini_k)
        self.entry_kakao.insert(0, kakao_k)
        
        if gemini_k and kakao_k:
            self.frame_api.pack_forget()
        
        # 검색 프레임
        frame_search = tk.Frame(root)
        frame_search.pack(fill='x', pady=10)
        
        tk.Label(frame_search, text="📍 지역:", font=("Helvetica", 12)).grid(row=0, column=0, pady=5)
        self.entry_loc = tk.Entry(frame_search, font=("Helvetica", 12), width=15)
        self.entry_loc.grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(frame_search, text="🍜 메뉴:", font=("Helvetica", 12)).grid(row=0, column=2, pady=5)
        self.entry_food = tk.Entry(frame_search, font=("Helvetica", 12), width=15)
        self.entry_food.grid(row=0, column=3, padx=5, pady=5)
        
        self.btn_search = tk.Button(frame_search, text="검색하기", font=("Helvetica", 12, "bold"), bg="#4CAF50", command=self.on_search)
        self.btn_search.grid(row=0, column=4, padx=5)
        
        self.btn_random = tk.Button(frame_search, text="다른곳 추천받기", font=("Helvetica", 12, "bold"), fg="black", bg="#FFA500", state='disabled', command=self.on_random_recommend)
        self.btn_random.grid(row=0, column=5, padx=5)
        
        # 로딩/상태 라벨
        self.status_label = tk.Label(root, text="", fg="blue")
        self.status_label.pack()
        
        # 결과 표시 프레임 (스크롤 가능)
        self.result_container = ScrollableFrame(root)
        self.result_container.pack(fill='both', expand=True, pady=10)
        
        self.images = [] # 가비지 컬렉션 방지용 이미지 리스트

    def on_save_keys(self):
        save_keys(self.entry_gemini.get().strip(), self.entry_kakao.get().strip())
        messagebox.showinfo("저장 완료", "두 개의 API 키가 저장되었습니다.")
        self.frame_api.pack_forget()

    def on_search(self):
        g_key = self.entry_gemini.get().strip()
        k_key = self.entry_kakao.get().strip()
        loc = self.entry_loc.get().strip()
        food = self.entry_food.get().strip()
        
        if not g_key or not k_key:
            messagebox.showwarning("API 키 누락", "Gemini 와 Kakao API 키를 모두 입력해주세요!")
            return
        if not loc:
            messagebox.showwarning("입력 누락", "지역을 입력해주세요.")
            return
            
        self.btn_search.config(state='disabled')
        self.status_label.config(text="⏳ AI가 최적의 검색어를 분석하고 실제 지도를 탐색 중입니다...", fg="blue")
        
        # 기존 결과 초기화
        for widget in self.result_container.scrollable_frame.winfo_children():
            widget.destroy()
        self.images.clear()
        self.shown_places = set()
        
        threading.Thread(target=self.do_search, args=(g_key, k_key, loc, food), daemon=True).start()

    def do_search(self, g_key, k_key, loc, food):
        try:
            # 1. Gemini로 검색어 추출
            keyword = get_search_keyword(g_key, loc, food)
            self.root.after(0, lambda: self.status_label.config(text=f"🔍 '{keyword}' (으)로 카카오맵 탐색 중..."))
            
            # 2. Kakao Local API 호출
            places = search_kakao_places(k_key, keyword)
            
            # 주소 필터링 (사용자 입력 지역이 실제 주소에 포함된 곳만)
            loc_words = loc.split()
            filtered_places = []
            for p in places:
                addr = p.get('road_address_name', '') + " " + p.get('address_name', '')
                if all(w in addr for w in loc_words):
                    filtered_places.append(p)
                    
            if not filtered_places:
                self.root.after(0, self.show_error, f"입력하신 지역('{loc}') 내에 '{keyword}' 관련 맛집이 없습니다.")
                return
                
            # 상태 저장 (다른곳 추천받기용)
            self.current_filtered_places = filtered_places
            self.current_loc = loc
            self.current_k_key = k_key
            
            # 추천 개수 조절 (아무거나=5개, 특정메뉴=3개)
            target_count = 5 if not food or food == '아무거나' else 3
            final_places = random.sample(filtered_places, min(len(filtered_places), target_count))
                
            self.render_places(final_places)
            
        except Exception as e:
            self.root.after(0, self.show_error, str(e))

    def on_random_recommend(self):
        if not hasattr(self, 'current_filtered_places') or not self.current_filtered_places:
            return
            
        self.btn_random.config(state='disabled')
        self.btn_search.config(state='disabled')
        self.status_label.config(text="⏳ 새로운 맛집을 아래에 추가 중입니다...", fg="blue")
        
        available_places = [p for p in self.current_filtered_places if p.get('place_url') not in self.shown_places]
        if not available_places:
            self.status_label.config(text="ℹ️ 해당 조건으로 찾은 맛집을 모두 보여드렸습니다.", fg="orange")
            self.btn_random.config(state='normal')
            self.btn_search.config(state='normal')
            return
            
        target_count = 3
        final_places = random.sample(available_places, min(len(available_places), target_count))
        
        threading.Thread(target=self.render_places, args=(final_places,), daemon=True).start()

    def render_places(self, places):
        try:
            for place in places:
                name = place.get('place_name')
                address = place.get('road_address_name') or place.get('address_name')
                phone = place.get('phone') or '전화번호 없음'
                url = place.get('place_url')
                
                if url:
                    self.shown_places.add(url)
                
                # 이미지 가져오기
                img_url = search_kakao_image(self.current_k_key, f"{self.current_loc} {name}")
                photo = None
                if img_url:
                    try:
                        resp = requests.get(img_url, timeout=3)
                        img = Image.open(BytesIO(resp.content))
                        img.thumbnail((150, 150))
                        photo = ImageTk.PhotoImage(img)
                        self.images.append(photo) # GC 방지
                    except:
                        pass
                
                # UI 추가 (메인 스레드에서)
                self.root.after(0, self.add_place_ui, name, address, phone, url, photo)
                
            self.root.after(0, self.finish_search, "✅ 검색 완료!")
            self.root.after(0, lambda: self.btn_random.config(state='normal'))

            
        except Exception as e:
            self.root.after(0, self.show_error, str(e))

    def add_place_ui(self, name, address, phone, url, photo):
        frame = tk.Frame(self.result_container.scrollable_frame, bg="white", bd=0, padx=15, pady=15, highlightbackground="#dcdcdc", highlightthickness=1)
        frame.pack(fill='x', padx=10, pady=5)
        
        # 왼쪽 이미지 영역 (픽셀 크기 강제 고정)
        img_frame = tk.Frame(frame, width=150, height=150, bg="#f5f5f5")
        img_frame.pack_propagate(False)
        img_frame.pack(side='left', padx=(0, 15))
        
        lbl_img = tk.Label(img_frame, text="사진 없음", bg="#f5f5f5")
        if photo:
            lbl_img.config(image=photo, text="")
        lbl_img.pack(expand=True, fill='both')
        
        # 오른쪽 텍스트 정보
        info_frame = tk.Frame(frame, bg="white")
        info_frame.pack(side='left', fill='both', expand=True)
        
        tk.Label(info_frame, text=name, bg="white", font=("Helvetica", 16, "bold"), fg="#1a0dab").pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"📍 주소: {address}", bg="white", font=("Helvetica", 12)).pack(anchor='w', pady=2)
        tk.Label(info_frame, text=f"📞 전화: {phone}", bg="white", font=("Helvetica", 12)).pack(anchor='w', pady=2)
        
        # 버튼 프레임
        btn_frame = tk.Frame(info_frame, bg="white")
        btn_frame.pack(anchor='w', pady=5)
        
        # 주소 복사 버튼
        def copy_addr(a=address):
            self.root.clipboard_clear()
            self.root.clipboard_append(a)
            messagebox.showinfo("복사 완료", "주소가 클립보드에 복사되었습니다.")
            
        tk.Button(btn_frame, text="주소 복사", command=copy_addr).pack(side='left', padx=(0, 5))
        
        # 지도 열기 버튼
        def open_link(u=url):
            if u:
                webbrowser.open(u)
            else:
                messagebox.showinfo("안내", "제공된 식당 상세 링크가 없습니다.")
                
        tk.Button(btn_frame, text="상세보기 (카카오맵 열기)", command=open_link).pack(side='left')

    def show_error(self, msg):
        self.status_label.config(text="❌ 오류 발생", fg="red")
        messagebox.showerror("오류", msg)
        self.btn_search.config(state='normal')

    def finish_search(self, msg):
        self.status_label.config(text=msg, fg="green")
        self.btn_search.config(state='normal')

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
