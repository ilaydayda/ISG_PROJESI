import easyocr
import cv2
from PIL import Image
from pillow_heif import register_heif_opener
import os
import re
import pymongo
import pandas as pd
import certifi
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# HEIC (iPhone) Desteği
register_heif_opener()

# --- 1. AYARLAR ---
URI = "mongodb+srv://ilaydanyilmaz_db_user:EAtzyxmF1ji6KK1Q@cluster0.ef9qbof.mongodb.net/?appName=Cluster0"
DB_NAME = "KimyaProjesi"
COLLECTION_NAME = "Envanter"

RESIM_KLASORU = "denemegoruntuleri" 
EXCEL_CIKTI_ADI = "Fine_Kinney_Risk_Analizi.xlsx"
cas_kodu_sablonu = r'\b\d{2,7}-\d{2}-\d\b'

# Şiddet puanına göre Risk Tanımı Sözlüğü (Gönderdiğin tabloya göre oluşturuldu)
RISK_TANIMLARI = {
    100: "Kitlesel patlama, aşırı alevlenir gazlar, solunması halinde ölüm.",
    40: "Yutulması halinde ölüm, kanserojen etki, genetik hasar.",
    15: "Ciddi cilt yanıkları, kalıcı göz hasarı, organ hasarı.",
    7: "Zararlı (akut), ciddi alerjik reaksiyonlar, astım belirtileri.",
    3: "Cilt tahrişi, göz tahrişi, uyuşukluk veya baş dönmesi.",
    1: "Sadece çevresel hafif zararlar, insana doğrudan etkisi düşük."
}

def projeyi_baslat():
    client = pymongo.MongoClient(URI)
    return client[DB_NAME][COLLECTION_NAME]

def risk_derecesi_hesapla(skor):
    if skor < 20: return "Kabul Edilebilir Risk"
    elif skor < 70: return "Dikkate Değer Risk"
    elif skor < 200: return "Önemli Risk"
    elif skor < 400: return "Yüksek Risk"
    else: return "Çok Yüksek Risk"

# --- 2. GÖRÜNTÜ İŞLEME VE OCR FONKSİYONU ---
def goruntuden_cas_oku(dosya_yolu, reader):
    print(f"\n🔍 {os.path.basename(dosya_yolu)} taranıyor...")
    
    gecici_png = "gecici_ham.png"
    islenmis_png = "gecici_islenmis.png"

    try:
        # 1. HEIC/PNG/JPG fark etmeksizin standart ve KAYIPSIZ PNG'ye çevir
        resim = Image.open(dosya_yolu)
        resim.convert('RGB').save(gecici_png, "PNG")

        # 2. OPENCV İLE GÖRÜNTÜ İŞLEME BAŞLIYOR (Colab'daki mantık)
        img = cv2.imread(gecici_png)

        # Resmi 2 kat büyütüyoruz (küçük detaylar ortaya çıksın)
        img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

        # Resmi gri tona çeviriyoruz
        gri_resim = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Yazıları simsiyah, arka planı bembeyaz yapıyoruz (Eşikleme - 120 değeri)
        _, siyah_beyaz_resim = cv2.threshold(gri_resim, 120, 255, cv2.THRESH_BINARY)

        # İşlenmiş resmi kaydediyoruz
        cv2.imwrite(islenmis_png, siyah_beyaz_resim)

        # 3. İŞLENMİŞ TERTEMİZ RESMİ EASYOCR'A VERİYORUZ
        sonuclar = reader.readtext(islenmis_png)
        bulunan_cas_kodlari = []

        for (koordinat, metin, guven_skoru) in sonuclar:
            metin = metin.strip()
            # Bazen OCR tireler arasına boşluk koyar, garantilemek için boşlukları siliyoruz
            metin = metin.replace(" ", "") 
            
            # Sadece katı kuralımıza uyanları alıyoruz
            if re.search(cas_kodu_sablonu, metin):
                bulunan_cas_kodlari.append(metin)

        return list(set(bulunan_cas_kodlari)) 

    except Exception as e:
        print(f"❌ Resim işlenirken hata oluştu: {e}")
        return []
        
    finally:
        # İşlem bitince arkamızda çöp dosya bırakmıyoruz
        if os.path.exists(gecici_png): 
            os.remove(gecici_png)
        if os.path.exists(islenmis_png): 
            os.remove(islenmis_png)

# --- 3. ANA AKIŞ VE EXCEL BİRLEŞTİRME ---
if __name__ == "__main__":
    try:
        koleksiyon = projeyi_baslat()
        print("OCR Modeli yükleniyor, lütfen bekleyin...")
        reader = easyocr.Reader(['en'])

        if not os.path.exists(RESIM_KLASORU):
            print(f" HATA: '{RESIM_KLASORU}' klasörü bulunamadı.")
            exit()

        print("\n" + "="*40)
        secim = input(" Tüm klasörü mü taramak istersin (K) yoksa tek bir resmi mi (R)? [K/R]: ").upper()
        
        islenecek_dosyalar = []
        if secim == 'R':
            dosya_adi = input(" Resmin tam adını uzantısıyla yazın (örn: deneme1.png): ")
            tam_yol = os.path.join(RESIM_KLASORU, dosya_adi)
            if os.path.exists(tam_yol):
                islenecek_dosyalar.append(dosya_adi)
            else:
                print(" Dosya bulunamadı!")
                exit()
        else:
            desteklenen_uzantilar = (".png", ".jpg", ".jpeg", ".heic")
            islenecek_dosyalar = [f for f in os.listdir(RESIM_KLASORU) if f.lower().endswith(desteklenen_uzantilar)]

        if not islenecek_dosyalar:
            print(" İşlenecek resim bulunamadı.")
            exit()

        excel_satirlari = []
        sira_no = 1

        for dosya in islenecek_dosyalar:
            tam_yol = os.path.join(RESIM_KLASORU, dosya)
            bulunan_caslar = goruntuden_cas_oku(tam_yol, reader)

            if not bulunan_caslar:
                print(" Bu resimde CAS bulunamadı.")
                continue

            for cas in bulunan_caslar:
                print(f"   -> Veritabanında aranıyor: {cas}...")
                db_verisi = koleksiyon.find_one({"cas_no": cas})

                if db_verisi:
                    kimyasal_adi = db_verisi.get('kimyasal_adi', 'Bilinmeyen')
                    tehlike_yeri = f"{cas} - {kimyasal_adi}"
                    
                    # Veritabanından değerleri çekiyoruz
                    h_ifadeleri = db_verisi.get("h_ifadeleri", [])
                    olasilik = db_verisi.get("olasilik_puani", "")
                    siddet = db_verisi.get("siddet_puani", "")
                    
                    # 1) H kodlarını tek bir hücrede alt alta yazılacak şekilde birleştiriyoruz
                    if h_ifadeleri:
                        tehlike_tanimi = "\n".join([f"{h.get('kod', '')}: {h.get('aciklama', '')}" for h in h_ifadeleri])
                    else:
                        tehlike_tanimi = "Veritabanında H kodu bulunamadı."

                    # 2) Şiddet Puanına göre Risk Tanımını Belirle
                    risk_tanimi = ""
                    if siddet != "":
                        try:
                            # Şiddet puanını integer'a çevirip sözlükten arıyoruz
                            risk_tanimi = RISK_TANIMLARI.get(int(siddet), "Bilinmeyen risk seviyesi")
                        except ValueError:
                            risk_tanimi = "Geçersiz şiddet puanı formatı"
                    
                    # 3) Kullanıcıdan Frekans (F) iste
                    frekans = ""
                    risk_skoru = ""
                    risk_derecesi = ""
                    
                    print(f"\n💡 Kimyasal Bulundu: {kimyasal_adi} (Olasılık: {olasilik}, Şiddet: {siddet})")
                    while True:
                        frekans_input = input(f"👉 Lütfen bu kimyasal için FREKANS değerini girin: ")
                        try:
                            frekans = float(frekans_input.replace(',', '.'))
                            break
                        except ValueError:
                            print("❌ Hatalı giriş! Lütfen sadece sayısal bir değer girin (örn: 3 veya 0.5)")

                    # 4) Risk Skoru ve Derecesi Hesapla
                    try:
                        risk_skoru = float(olasilik) * float(siddet) * frekans
                        risk_derecesi = risk_derecesi_hesapla(risk_skoru)
                        print(f"✅ Risk Skoru: {risk_skoru} -> Derece: {risk_derecesi}")
                    except (ValueError, TypeError):
                        print("⚠️ Olasılık veya şiddet eksik olduğu için Risk Skoru hesaplanamadı.")

                    # Excel satırını oluştur ve ekle
                    excel_satirlari.append({
                        "No": sira_no,
                        "Tehlike yeri Bölüm/Birim": tehlike_yeri,
                        "Tehlike Tanımı": tehlike_tanimi,
                        "Risk Tanımı": risk_tanimi, 
                        "Olasılık": olasilik,
                        "Şiddet": siddet,
                        "Frekans": frekans, 
                        "Risk Skoru": risk_skoru, 
                        "Risk Derecesi": risk_derecesi, 
                        "Aksiyon (Alınacak Tedbirler)": ""
                    })
                    sira_no += 1
                    
                else:
                    print(f"  DİKKAT: {cas} veritabanında (MSDS) bulunamadı!")

        # --- 4. EXCEL DOSYASINI OLUŞTURMA ---
        if excel_satirlari:
            print("\n Excel (Fine Kinney) raporu oluşturuluyor...")
            df = pd.DataFrame(excel_satirlari)
            
            with pd.ExcelWriter(EXCEL_CIKTI_ADI, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Risk Analizi')
                
            print(f" BAŞARILI! Tüm veriler '{EXCEL_CIKTI_ADI}' dosyasına aktarıldı.")
        else:
            print("\nEşleşen kayıt bulunamadığı için Excel oluşturulmadı.")

    except Exception as e:
        print(f"Kritik bir hata oluştu: {e}")

        print(f"❌ Kritik bir hata oluştu: {e}")

