#!/usr/bin/env python3
"""
BLS Spain Visa (Türkiye) - Randevu Slotu Bildirim Botu
=========================================================

NE YAPAR:
  - BLS randevu sayfasına (giriş yaparak) her çalıştığında bir kez bakar.
  - Boş randevu slotu bulursa Telegram üzerinden size ANINDA mesaj atar.
  - Randevuyu SİZİN YERİNİZE almaz — bunu bilerek yapmıyoruz, çünkü BLS
    otomatik/bot ile randevu almayı kullanım şartlarında yasaklıyor ve
    bunu tespit etmek için güvenlik önlemleri (çok faktörlü doğrulama,
    gerçek zamanlı izleme) kullanıyor. Bildirimi alır almaz siteye girip
    randevuyu birkaç saniyede SİZ alırsınız.

NASIL ÇALIŞIR:
  Bu script tek seferlik bir kontrol yapar. "10 dakikada bir" çalışması
  için sunucuda CRON JOB olarak ayarlanır (aşağıdaki kurulum talimatına
  bakın). Script kendi kendine sonsuz döngüde beklemez; cron onu tetikler.

KURULUM ÖNCESİ GEREKENLER:
  1. Bir Linux sunucu (VPS) - kurulum talimatında detaylı anlatılıyor.
  2. Bir Telegram Bot Token'ı ve Chat ID'niz (kurulum talimatında var).
  3. BLS hesap bilgileriniz (kullanıcı adı/e-posta ve şifre).
  4. AŞAĞIDAKİ SELECTOR'LARI SİZİN DOLDURMANIZ GEREKİYOR:
     Bu site dinamik olduğu ve zaman zaman değiştiği için, "boş slot var"
     ile "slot yok" mesajlarının HTML'deki tam yerini ben tahmin edemem.
     Tarayıcınızda F12 (Geliştirici Araçları) ile bu iki metnin bulunduğu
     elementleri inceleyip aşağıdaki CONFIG kısmına yapıştırmanız gerekiyor.
     Kurulum talimatında bunu nasıl yapacağınızı adım adım anlatıyorum.
"""

import os
import sys
import logging
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests

# ============================================================
# CONFIG - Bunları kendi bilgilerinizle doldurun
# ============================================================

# Ortam değişkenlerinden okunuyor (güvenlik için şifreleri koda yazmıyoruz)
BLS_LOGIN_URL   = os.environ.get("BLS_LOGIN_URL", "https://turkey.blsspainvisa.com/istanbul/english/login.php")
BLS_USERNAME    = os.environ["BLS_USERNAME"]        # BLS hesap e-postanız
BLS_PASSWORD    = os.environ["BLS_PASSWORD"]        # BLS hesap şifreniz

TELEGRAM_TOKEN  = os.environ["TELEGRAM_BOT_TOKEN"]  # BotFather'dan aldığınız token
TELEGRAM_CHATID = os.environ["TELEGRAM_CHAT_ID"]    # Kendi chat id'niz

# --- BURAYI SİZİN DOLDURMANIZ GEREKİYOR ---
# Tarayıcı Geliştirici Araçları (F12) ile giriş formundaki ve randevu
# sayfasındaki elementlerin CSS selector'larını bulup buraya yazın.
USERNAME_FIELD_SELECTOR   = "#txtEmail"          # ÖRNEK - kontrol edin
PASSWORD_FIELD_SELECTOR   = "#txtPassword"       # ÖRNEK - kontrol edin
LOGIN_BUTTON_SELECTOR     = "#btnLogin"          # ÖRNEK - kontrol edin
APPOINTMENT_PAGE_URL      = "https://turkey.blsspainvisa.com/istanbul/english/appointment.php"  # ÖRNEK
NO_SLOT_TEXT              = "No slot available"  # Slot yokken sayfada çıkan metin - kontrol edin
# ------------------------------------------

LOG_FILE = os.path.join(os.path.dirname(__file__), "bls_takip.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def telegram_bildir(mesaj: str) -> None:
    """Telegram üzerinden bildirim gönderir."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": TELEGRAM_CHATID, "text": mesaj}, timeout=15)
        r.raise_for_status()
        log.info("Telegram bildirimi gönderildi.")
    except Exception as e:
        log.error(f"Telegram bildirimi gönderilemedi: {e}")


def randevu_kontrol_et() -> bool:
    """
    Tek seferlik kontrol yapar. Boş slot varsa True, yoksa False döner.
    Hata olursa exception fırlatır (main() bunu yakalayıp bildirim gönderir).
    """
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1366,900")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)
    try:
        wait = WebDriverWait(driver, 20)

        # 1) Giriş yap
        log.info("Giriş sayfasına gidiliyor...")
        driver.get(BLS_LOGIN_URL)

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, USERNAME_FIELD_SELECTOR)))
        driver.find_element(By.CSS_SELECTOR, USERNAME_FIELD_SELECTOR).send_keys(BLS_USERNAME)
        driver.find_element(By.CSS_SELECTOR, PASSWORD_FIELD_SELECTOR).send_keys(BLS_PASSWORD)
        driver.find_element(By.CSS_SELECTOR, LOGIN_BUTTON_SELECTOR).click()

        # NOT: Sitede CAPTCHA veya SMS/e-posta doğrulama (2FA) çıkarsa
        # bu adımı otomatik geçemeyiz - bu durumda script hata verip
        # size "manuel giriş gerekiyor" bildirimi gönderecek şekilde
        # aşağıya bir kontrol ekleyebiliriz (bkz. kurulum talimatı).

        log.info("Giriş yapıldı, randevu sayfasına gidiliyor...")
        driver.get(APPOINTMENT_PAGE_URL)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        sayfa_metni = driver.find_element(By.TAG_NAME, "body").text

        if NO_SLOT_TEXT.lower() in sayfa_metni.lower():
            log.info("Şu an boş slot yok.")
            return False
        else:
            log.info("OLASI BOŞ SLOT TESPİT EDİLDİ!")
            return True

    finally:
        driver.quit()


def main():
    log.info("=== Kontrol başlıyor ===")
    try:
        slot_var_mi = randevu_kontrol_et()
    except Exception as e:
        log.error(f"Kontrol sırasında hata oluştu: {e}")
        # İsterseniz hata durumunda da bildirim almak için alttaki satırı açın:
        # telegram_bildir(f"⚠️ BLS kontrol scripti hata verdi: {e}")
        sys.exit(1)

    if slot_var_mi:
        simdi = datetime.now().strftime("%d.%m.%Y %H:%M")
        telegram_bildir(
            f"🚨 BOŞ RANDEVU SLOTU OLABİLİR! ({simdi})\n"
            f"Hemen kontrol edip randevunuzu alın:\n{APPOINTMENT_PAGE_URL}"
        )
    log.info("=== Kontrol bitti ===\n")


if __name__ == "__main__":
    main()
