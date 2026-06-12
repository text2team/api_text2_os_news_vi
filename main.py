from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import feedparser
import time
import re
import urllib.request
import json
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RAM Cache structure separated by region
cache = {
    "VN": {"data": [], "last_updated": 0},
    "INTL": {"data": [], "last_updated": 0}
}
CACHE_TIME = 300 # Keep for 5 minutes

VIETNAM_FEEDS = {
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

INTERNATIONAL_FEEDS = {
    "BBC News": "http://feeds.bbci.co.uk/news/rss.xml",
    "CNN": "http://rss.cnn.com/rss/edition_world.rss",
    "The New York Times": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
    "WSJ": "https://feeds.a.dj.com/rss/RSSWSJTopStories.xml",
    "NPR": "https://feeds.npr.org/1001/rss.xml",
    "Financial Times": "https://www.ft.com/?format=rss"
}

SOURCE_LOGOS = {
    # International Logos
    "BBC News": "https://upload.wikimedia.org/wikipedia/commons/6/62/BBC_News_2019.svg",
    "CNN": "https://upload.wikimedia.org/wikipedia/commons/b/b1/CNN.svg",
    "The New York Times": "https://upload.wikimedia.org/wikipedia/commons/4/40/New_York_Times_logo_variation.jpg",
    "WSJ": "https://upload.wikimedia.org/wikipedia/commons/4/4e/WSJ_Logo.png",
    "NPR": "https://upload.wikimedia.org/wikipedia/commons/d/d7/National_Public_Radio_logo.svg",
    "Financial Times": "https://upload.wikimedia.org/wikipedia/commons/4/47/Financial_Times_corporate_logo.png",
    
    # Vietnam Logos
    "Tuổi Trẻ": "https://upload.wikimedia.org/wikipedia/commons/b/b5/Logo_B%C3%A1o_Tu%E1%BB%95i_Tr%E1%BA%BB.svg",
    "Thanh Niên": "https://upload.wikimedia.org/wikipedia/commons/e/ea/Thanh_Ni%C3%AAn_logo.svg",
    "Thể Thao 247": "https://thethao247.vn/assets/images/logo.png",
    "VTV": "https://upload.wikimedia.org/wikipedia/commons/0/07/VTV_Logo_2013.svg",
    "VnExpress": "https://upload.wikimedia.org/wikipedia/commons/e/e3/VnExpress.net_Logo.svg",
    "Báo Lao Động": "https://laodong.vn/favicon.ico",
    "Báo Nhân Dân": "https://upload.wikimedia.org/wikipedia/commons/8/87/Bao_Nhan_Dan_logo.png",
    "Báo Pháp Luật TP HCM": "https://plo.vn/favicon.ico",
    "VTV Công Nghệ": "https://upload.wikimedia.org/wikipedia/commons/0/07/VTV_Logo_2013.svg",
    "Genk": "https://genk.vn/favicon.ico",
    "VTC": "https://vtcnews.vn/images/logos/logo.png"
}

# In-memory IP GeoIP cache to prevent API spam (expires in 24 hours)
ip_to_country_cache = {}

def get_client_ip(request: Request) -> str:
    """Extract client IP addressing proxy/CDN headers."""
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()
    return request.client.host if request.client else "127.0.0.1"

def get_country_from_ip(ip: str) -> str:
    """Retrieve country code from client IP via public API with caching."""
    # Local/internal IPs default to Vietnam for easy testing and local usage
    if (ip == "127.0.0.1" or 
        ip.startswith("192.168.") or 
        ip.startswith("10.") or 
        ip.startswith("172.") or 
        ip == "localhost" or
        ip == "::1"):
        return "VN"
        
    current_time = time.time()
    if ip in ip_to_country_cache:
        country, expires = ip_to_country_cache[ip]
        if current_time < expires:
            return country
            
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,countryCode"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=1.5) as response:
            res_data = json.loads(response.read().decode())
            if res_data.get("status") == "success":
                country = res_data.get("countryCode", "VN")
                ip_to_country_cache[ip] = (country, current_time + 86400)
                return country
    except Exception as e:
        print(f"GeoIP look up failed for {ip}: {e}")
        
    return "VN"

def detect_region(request: Request, country_param: str = None) -> str:
    """Detect request region (VN vs INTL) based on param, CDN headers, locale, and IP."""
    # 1. Query parameter override
    if country_param:
        country_param = country_param.upper().strip()
        if country_param in ["VN", "VIETNAM", "VI"]:
            return "VN"
        return "INTL"
        
    # 2. CDN headers (Cloudflare, Vercel, AWS CloudFront, etc.)
    for header in ["cf-ipcountry", "x-vercel-ip-country", "cloudfront-viewer-country", "x-country-code"]:
        val = request.headers.get(header)
        if val:
            val = val.upper().strip()
            return "VN" if val == "VN" else "INTL"
            
    # 3. Accept-Language header hint
    accept_lang = request.headers.get("accept-language", "").lower()
    if "vi" in accept_lang:
        return "VN"
        
    # 4. Fallback: GeoIP lookup
    ip = get_client_ip(request)
    country = get_country_from_ip(ip)
    return "VN" if country == "VN" else "INTL"

async def fetch_source_articles(source: str, url: str) -> tuple:
    try:
        # Run feedparser.parse in a separate thread so it doesn't block the asyncio event loop
        feed = await asyncio.to_thread(feedparser.parse, url)
        
        channel_avatar = ""
        if 'image' in feed.feed and 'href' in feed.feed.image:
            channel_avatar = feed.feed.image.href
        else:
            channel_avatar = SOURCE_LOGOS.get(source, "https://text-2.com/media/thumnel.png")
            
        articles = []
        for entry in feed.entries[:15]:
            image_url = ""
            
            # 1. Standard media tag scanning
            if 'media_content' in entry and len(entry.media_content) > 0:
                image_url = entry.media_content[0].get('url', '')
            elif 'media_thumbnail' in entry and len(entry.media_thumbnail) > 0:
                image_url = entry.media_thumbnail[0].get('url', '')
                
            # 2. Enclosure tag scanning
            if not image_url and 'links' in entry:
                for link in entry.links:
                    if link.get('rel') == 'enclosure' and (
                        'image' in link.get('type', '').lower() or 
                        link.get('href', '').lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif'))
                    ):
                        image_url = link.get('href', '')
                        break
                        
            # 3. Rare direct image tag
            if not image_url and 'image' in entry and 'href' in getattr(entry, 'image', {}):
                image_url = entry.image.href
                
            # 4. Regex HTML fallback scanning
            if not image_url:
                html_content = entry.get("summary", "")
                if "content" in entry and len(entry.content) > 0:
                    html_content += entry.content[0].get("value", "")
                if "description" in entry:
                    html_content += entry.get("description", "")
                    
                match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
                if match:
                    image_url = match.group(1)
                    
            # 5. Default placeholder image
            if not image_url:
                image_url = "https://text-2.com/assets/default-news.jpg"
                
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "image": image_url,
                "source": source,
                "source_avatar": channel_avatar,
                "published": entry.get("published", "")
            })
        return source, articles
    except Exception as e:
        print(f"Error parsing RSS source {source}: {e}")
        return source, []

async def feed_generator(feeds_to_parse: dict, region: str):
    tasks = [fetch_source_articles(source, url) for source, url in feeds_to_parse.items()]
    all_articles = []
    
    for future in asyncio.as_completed(tasks):
        try:
            source, articles = await future
            if articles:
                all_articles.extend(articles)
                # Yield this chunk as a single line JSON chunk
                yield json.dumps({"status": "progress", "source": source, "data": articles}, ensure_ascii=False) + "\n"
        except Exception as e:
            print(f"Error in stream fetch: {e}")
            
    # Update RAM cache at the end of the stream
    if all_articles:
        cache[region]["data"] = all_articles
        cache[region]["last_updated"] = time.time()
        
    yield json.dumps({"status": "done"}, ensure_ascii=False) + "\n"

@app.get("/api/news")
async def get_news(request: Request, country: str = None, stream: bool = False):
    region = detect_region(request, country)
    current_time = time.time()
    
    region_cache = cache[region]
    
    # Return RAM Cache if valid (5 minutes) and not streaming
    if not stream and current_time - region_cache["last_updated"] < CACHE_TIME and region_cache["data"]:
        return {
            "status": "success", 
            "source": f"RAM Cache ({region} - Siêu tốc)", 
            "data": region_cache["data"]
        }
        
    feeds_to_parse = VIETNAM_FEEDS if region == "VN" else INTERNATIONAL_FEEDS
    
    if stream:
        return StreamingResponse(
            feed_generator(feeds_to_parse, region),
            media_type="application/x-ndjson"
        )
    else:
        # Fast concurrent fetch for standard requests
        tasks = [fetch_source_articles(source, url) for source, url in feeds_to_parse.items()]
        results = await asyncio.gather(*tasks)
        
        news_data = []
        for source, articles in results:
            if articles:
                news_data.extend(articles)
                
        # Update cache
        if news_data:
            cache[region]["data"] = news_data
            cache[region]["last_updated"] = current_time
            
        return {
            "status": "success", 
            "source": f"Cào Live Nhanh ({region})", 
            "data": news_data
        }
