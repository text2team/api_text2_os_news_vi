from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import feedparser
import time
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cache = {"data": [], "last_updated": 0}
CACHE_TIME = 300 # Giữ 5 phút

RSS_FEEDS = {
    "Tuổi Trẻ": "https://tuoitre.vn/rss/tin-moi-nhat.rss",
    "Thanh Niên": "https://thanhnien.vn/rss/home.rss",
    "Thể Thao 247": "https://thethao247.vn/trang-chu.rss",
    "VTV": "https://vtv.vn/rss/home.rss",
    "VnExpress": "https://vnexpress.net/rss/tin-moi-nhat.rss",
    "Báo Lao Động": "https://laodong.vn/rss/home.rss",
    "Báo Nhân Dân": "https://nhandan.vn/rss/home.rss",
    "Báo Pháp Luật TP HCM": "https://plo.vn/rss/home.rss",
    "VTV Công Nghệ": "https://vtv.vn/rss/cong-nghe.rss",
    "Genk": "https://genk.vn/rss/home.rss",
    "VTC": "https://vtcnews.vn/rss/trang-chu.rss"
    
    
}

@app.get("/api/news")
def get_news():
    current_time = time.time()
    
    if current_time - cache["last_updated"] < CACHE_TIME and cache["data"]:
        return {"status": "success", "source": "RAM Cache (Siêu tốc)", "data": cache["data"]}
    
    news_data = []
    for source, url in RSS_FEEDS.items():
        feed = feedparser.parse(url)
        for entry in feed.entries[:10]:
            image_url = ""
            # Trích xuất link ảnh từ thẻ summary
            if "summary" in entry:
                match = re.search(r'src=["\'](.*?)["\']', entry.summary)
                if match:
                    image_url = match.group(1)

            news_data.append({
                "title": entry.title,
                "link": entry.link,
                "image": image_url,
                "source": source,
                "published": entry.get("published", "")
            })
    
    cache["data"] = news_data
    cache["last_updated"] = current_time
    
    return {"status": "success", "source": "Cào Live Mới Nhất", "data": news_data}