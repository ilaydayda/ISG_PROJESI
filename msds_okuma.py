import fitz  # PyMuPDF
import re
import pymongo
import os
from deep_translator import GoogleTranslator

# --- AYARLAR ---
URI = "mongodb+srv://ilaydanyilmaz_db_user:EAtzyxmF1ji6KK1Q@cluster0.ef9qbof.mongodb.net/?appName=Cluster0"
DB_NAME = "KimyaProjesi"
COLLECTION_NAME = "Envanter"
KLASOR_ADI = "kaynak_msds" 

cevirmen = GoogleTranslator(source='auto', target='tr')

def projeyi_baslat():
    client = pymongo.MongoClient(URI)
    return client[DB_NAME][COLLECTION_NAME]

def msds_analiz_ve_cevir(pdf_yolu):
    dosya_adi = os.path.basename(pdf_yolu)
    doc = fitz.open(pdf_yolu)
    tam_metin = ""
    for sayfa in doc: tam_metin += sayfa.get_text()
    temiz_metin = " ".join(tam_metin.split())

    cas_match = re.search(r"CAS[^\d]{0,30}?(\d{2,7}-\d{2}-\d)", temiz_metin, re.IGNORECASE)
    cas_no = cas_match.group(1) if cas_match else "Bulunamadı"

    if cas_no == "Bulunamadı": return None

    ad_match = re.search(r"(?:Ürün adı|Madde/Müstahzar adı|Kimyasal Adı|Product name)[^\w]*([A-Za-z0-9\-\s\(\)]{3,50}?)(?=\s(?:Product|REACH|CAS|1\.\d))", temiz_metin, re.IGNORECASE)
    kimyasal_adi = ad_match.group(1).strip() if ad_match else dosya_adi.replace(".pdf", "")

    h_bulunanlar = re.findall(r"(H\d{3})\s+([^\n\"]+)", tam_metin)
    p_bulunanlar = re.findall(r"(P\d{3}(?:\+P?\d{3})*)\s+([^\n\"]+)", tam_metin)

    h_listesi = [{"kod": k.strip(), "aciklama": a.strip()} for k, a in h_bulunanlar]
    p_listesi = [{"kod": k.strip().replace("$", ""), "aciklama": a.strip()} for k, a in p_bulunanlar]
    
    h_listesi = [dict(t) for t in {tuple(d.items()) for d in h_listesi}]
    p_listesi = [dict(t) for t in {tuple(d.items()) for d in p_listesi}]

    print(f"   🔄 {cas_no} için H ve P kodları Türkçeye çevriliyor...")
    for h in h_listesi:
        try: h['aciklama'] = cevirmen.translate(h['aciklama'])
        except: pass
    
    for p in p_listesi:
        try: p['aciklama'] = cevirmen.translate(p['aciklama'])
        except: pass

    return {
        "kimyasal_adi": kimyasal_adi,
        "cas_no": cas_no,
        "h_ifadeleri": sorted(h_listesi, key=lambda x: x["kod"]),
        "p_ifadeleri": sorted(p_listesi, key=lambda x: x["kod"]),
        "dosya_kaynagi": dosya_adi
    }

if __name__ == "__main__":
    koleksiyon = projeyi_baslat()
    
    if not os.path.exists(KLASOR_ADI):
        os.makedirs(KLASOR_ADI)
        
    dosyalar = [f for f in os.listdir(KLASOR_ADI) if f.lower().endswith(".pdf")]
    
    if not dosyalar:
        print(f"⚠️ '{KLASOR_ADI}' klasöründe PDF bulunamadı.")
    else:
        print(f"🚀 Toplam {len(dosyalar)} MSDS taranıyor ve Türkçeye çevriliyor...\n")

        for dosya in dosyalar:
            tam_yol = os.path.join(KLASOR_ADI, dosya)
            veri = msds_analiz_ve_cevir(tam_yol)
            
            if veri:
                koleksiyon.update_one({"cas_no": veri["cas_no"]}, {"$set": veri}, upsert=True)
                print(f"✅ Veritabanına Eklendi: {veri['kimyasal_adi']} (CAS: {veri['cas_no']})")

        print("\n🎉 İşlem tamamlandı! Veritabanı güncel.")