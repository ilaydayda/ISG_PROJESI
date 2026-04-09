import easyocr
import cv2
from PIL import Image
from pillow_heif import register_heif_opener
import os
import re
import pymongo
import pandas as pd

# HEIC (iPhone) Desteği
register_heif_opener()

# --- 1. AYARLAR ---
URI = "mongodb+srv://ilaydanyilmaz_db_user:EAtzyxmF1ji6KK1Q@cluster0.ef9qbof.mongodb.net/?appName=Cluster0"
DB_NAME = "KimyaProjesi"
COLLECTION_NAME = "Envanter"

RESIM_KLASORU = "kimyasal_resimleri" 
EXCEL_CIKTI_ADI = "Fine_Kinney_Risk_Analizi.xlsx"
cas_kodu_sablonu = r'\b\d{2,7}-\d{2}-\d\b'

def projeyi_baslat():
    client = pymongo.MongoClient(URI)
    return client[DB_NAME][COLLECTION_NAME]

# --- 2. GÖRÜNTÜ İŞLEME VE OCR FONKSİYONU ---
def goruntuden_cas_oku(dosya_yolu, reader):
    print(f"\n🔍 {os.path.basename(dosya_yolu)} taranıyor...")
    gecici_jpg = "gecici_isg.jpg"

    try:
        resim = Image.open(dosya_yolu)
        resim.thumbnail((1500, 1500)) 
        resim.convert('RGB').save(gecici_jpg)

        sonuclar = reader.readtext(gecici_jpg)
        bulunan_cas_kodlari = []

        for (koordinat, metin, guven_skoru) in sonuclar:
            metin = metin.strip()
            if re.search(cas_kodu_sablonu, metin):
                bulunan_cas_kodlari.append(metin)

        return list(set(bulunan_cas_kodlari)) 

    except Exception as e:
        print(f"❌ Resim işlenirken hata oluştu: {e}")
        return []
        
    finally:
        if os.path.exists(gecici_jpg): 
            os.remove(gecici_jpg)

# --- 3. ANA AKIŞ VE EXCEL BİRLEŞTİRME ---
if __name__ == "__main__":
    try:
        koleksiyon = projeyi_baslat()
        print("⚙️ OCR Modeli yükleniyor, lütfen bekleyin...")
        reader = easyocr.Reader(['en'])

        if not os.path.exists(RESIM_KLASORU):
            print(f"❌ HATA: '{RESIM_KLASORU}' klasörü bulunamadı.")
            exit()

        print("\n" + "="*40)
        secim = input("👉 Tüm klasörü mü taramak istersin (K) yoksa tek bir resmi mi (R)? [K/R]: ").upper()
        
        islenecek_dosyalar = []
        if secim == 'R':
            dosya_adi = input("📄 Resmin tam adını uzantısıyla yazın (örn: deneme1.png): ")
            tam_yol = os.path.join(RESIM_KLASORU, dosya_adi)
            if os.path.exists(tam_yol):
                islenecek_dosyalar.append(dosya_adi)
            else:
                print("❌ Dosya bulunamadı!")
                exit()
        else:
            desteklenen_uzantilar = (".png", ".jpg", ".jpeg", ".heic")
            islenecek_dosyalar = [f for f in os.listdir(RESIM_KLASORU) if f.lower().endswith(desteklenen_uzantilar)]

        if not islenecek_dosyalar:
            print("⚠️ İşlenecek resim bulunamadı.")
            exit()

        excel_satirlari = []
        sira_no = 1

        for dosya in islenecek_dosyalar:
            tam_yol = os.path.join(RESIM_KLASORU, dosya)
            bulunan_caslar = goruntuden_cas_oku(tam_yol, reader)

            if not bulunan_caslar:
                print("❌ Bu resimde CAS bulunamadı.")
                continue

            for cas in bulunan_caslar:
                print(f"   -> Veritabanında aranıyor: {cas}...")
                db_verisi = koleksiyon.find_one({"cas_no": cas})

                if db_verisi:
                    tehlike_yeri = f"{cas} - {db_verisi.get('kimyasal_adi', 'Bilinmeyen')}"
                    h_ifadeleri = db_verisi.get("h_ifadeleri", [])
                    
                    if not h_ifadeleri:
                        excel_satirlari.append({
                            "No": sira_no,
                            "Tehlike yeri Bölüm/Birim": tehlike_yeri,
                            "Tehlike Tanımı": "Veritabanında H kodu bulunamadı.",
                            "Risk Tanımı": "", "Olasılık": "", "Şiddet": "", "Frekans": "", 
                            "Risk Skoru": "", "Risk Derecesi": "", "Aksiyon (Alınacak Tedbirler)": ""
                        })
                        sira_no += 1
                        print("   ⚠️ Sadece kimyasal adı eklendi (H kodu yok).")
                    else:
                        # HER BİR H KODU İÇİN AYRI SATIR OLUŞTURUYORUZ (Çeviri yapmıyoruz, direkt yazıyoruz)
                        for h in h_ifadeleri:
                            kod = h.get('kod', '')
                            aciklama = h.get('aciklama', '')
                            
                            excel_satirlari.append({
                                "No": sira_no,
                                "Tehlike yeri Bölüm/Birim": tehlike_yeri,
                                "Tehlike Tanımı": f"{kod}: {aciklama}",
                                "Risk Tanımı": "", "Olasılık": "", "Şiddet": "", "Frekans": "", 
                                "Risk Skoru": "", "Risk Derecesi": "", "Aksiyon (Alınacak Tedbirler)": ""
                            })
                            sira_no += 1
                        print(f"   ✅ Hazır Türkçe veri çekildi! Excel'de {len(h_ifadeleri)} ayrı satıra bölündü.")
                else:
                    print(f"   ⚠️ DİKKAT: {cas} veritabanında (MSDS) bulunamadı!")

        # --- 4. EXCEL DOSYASINI OLUŞTURMA ---
        if excel_satirlari:
            print("\n📝 Excel (Fine Kinney) raporu oluşturuluyor...")
            df = pd.DataFrame(excel_satirlari)
            
            with pd.ExcelWriter(EXCEL_CIKTI_ADI, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='Risk Analizi')
                
            print(f"🎯 BAŞARILI! Tüm veriler '{EXCEL_CIKTI_ADI}' dosyasına aktarıldı.")
        else:
            print("\n⚠️ Eşleşen kayıt bulunamadığı için Excel oluşturulmadı.")

    except Exception as e:
        print(f"❌ Kritik bir hata oluştu: {e}")