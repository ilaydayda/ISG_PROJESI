
import fitz  # PyMuPDF
import re
import pymongo
import os
from deep_translator import GoogleTranslator
from h_kodlari_sozluk import h_kodu_aciklama_getir

# --- AYARLAR ---
URI = "mongodb+srv://ilaydanyilmaz_db_user:EAtzyxmF1ji6KK1Q@cluster0.ef9qbof.mongodb.net/?appName=Cluster0"
DB_NAME = "KimyaProjesi"
COLLECTION_NAME = "Envanter"
KLASOR_ADI = "kaynak_msds"

cevirmen = GoogleTranslator(source='auto', target='tr')


def projeyi_baslat():
    client = pymongo.MongoClient(URI)
    return client[DB_NAME][COLLECTION_NAME]



FIZIKSEL_HAL_HARITASI = [
    # (ingilizce anahtar kelime regex, türkçe karşılık, OLASILIK ALGORİTMASI İÇİN kategori)
    (r"\bgas(es)?\b",                     "Gaz",            "gaz"),
    (r"\baerosol\b",                       "Aerosol",        "gaz"),
    (r"\bvapor(s)?\b",                     "Buhar",          "gaz"),
    (r"\bfume(s)?\b",                      "Duman",          "gaz"),
    (r"\bpowder\b",                        "Toz",            "tozsivi"),
    (r"\bfine\s+powder\b",                 "İnce Toz",       "tozsivi"),
    (r"\bdust\b",                          "Toz",            "tozsivi"),
    (r"\bgranul\w*\b",                     "Granül",         "kati"),
    (r"\bpellet(s)?\b",                    "Pelet",          "kati"),
    (r"\bsolid\b",                         "Katı",           "kati"),
    (r"\bcrystal\w*\b",                    "Kristal",        "kati"),
    (r"\bflake(s)?\b",                     "Pul/Flake",      "kati"),
    (r"\bpaste\b",                         "Macun",          "tozsivi"),
    (r"\bgel\b",                           "Jel",            "tozsivi"),
    (r"\bviscous\s+liquid\b",              "Viskoz Sıvı",    "sivi"),
    (r"\bliquid\b",                        "Sıvı",           "sivi"),
]

# Bu kelimeler SADECE renk/koku bilgisidir; tek başına fiziksel hal SAYILMAZ.
# (ör. "Colourless", "Odourless" gördüğümüzde hal bilgisi yokmuş gibi davranacağız,
#  yukarıdaki harita zaten bunları eşleştirmez, bu liste sadece belge amaçlı.)


def section_9_1_blogunu_ayikla(tam_metin):

    baslangic_match = re.search(r"SECTION\s*9[:\.\s]", tam_metin, re.IGNORECASE)
    if not baslangic_match:
        return ""

    baslangic = baslangic_match.start()

    bitis_match = re.search(r"SECTION\s*10[:\.\s]", tam_metin[baslangic:], re.IGNORECASE)
    if bitis_match:
        bitis = baslangic + bitis_match.start()
    else:
        bitis = min(baslangic + 3000, len(tam_metin))  # güvenlik için makul bir pencere

    return tam_metin[baslangic:bitis]


def fiziksel_hal_coz(tam_metin):
    

    blok = section_9_1_blogunu_ayikla(tam_metin)
    if not blok:
        return "", ""

    # Etiketten sonraki ~120 karakterlik pencerelere bakıyoruz: bu, etiketin
    # değerinin genelde aynı satırda veya hemen sonrasında olmasından kaynaklı.
    etiket_pattern = r"(Physical\s+state|Form\s*/\s*Appearance|Form\b|Appearance)\s*[:\-]?\s*(.{0,120}?)(?=\n[A-Z][a-zçğıöşü]|$)"

    adaylar = []
    for m in re.finditer(etiket_pattern, blok, re.IGNORECASE | re.DOTALL):
        adaylar.append(m.group(2))

    # Hiç etiket bulunamadıysa, son çare olarak tüm 9.1 bloğuna bak
    # (bazı PDF'lerde etiket/değer aynı satırda yapışık olabilir).
    if not adaylar:
        adaylar.append(blok)

    for aday in adaylar:
        aday_temiz = aday.strip()
        for ing_pattern, tr_karsilik, kategori in FIZIKSEL_HAL_HARITASI:
            if re.search(ing_pattern, aday_temiz, re.IGNORECASE):
                return tr_karsilik, kategori

    # Anahtar kelime bulunamadı (örn. sadece "Colourless" gibi renk bilgisi
    # varsa) -> emin olamıyoruz, BOŞ bırak.
    return "", ""


# ============================================================
# OLASILIK (O) PUANI - Fiziksel Hal Algoritması
# ============================================================

# "Uçucu Sıvı" (6) ile "Sıvı (Uçucu olmayan)" (3) ayrımını netleştirebiliriz.

OLASILIK_PUANLARI = {
    "gaz":      10,   # Gaz veya Çok Uçucu Sıvı
    "tozsivi":  6,    # Uçucu Sıvı / İnce Toz (toz, gel, macun bu gruba eşlendi)
    "sivi":     3,    # Sıvı (Uçucu olmayan)
    "kati":     1,    # Katı / Granül
}


def olasilik_puani_hesapla(kategori):
    return OLASILIK_PUANLARI.get(kategori, "")



H_SIDDET_GRUPLARI = [
    ({"H200", "H201", "H224", "H330"}, 100),
    ({"H300", "H301", "H310", "H340", "H350"}, 40),
    ({"H314", "H318", "H370", "H372"}, 15),
    ({"H302", "H312", "H332", "H317"}, 7),
    ({"H315", "H319", "H335", "H336"}, 3),
    ({"H402", "H412"}, 1),
]


def siddet_puani_hesapla(h_ifadeleri):
    """
    h_ifadeleri: [{"kod": "H315", "aciklama": "..."}, ...]
    Birden fazla H kodu varsa en yüksek şiddet puanını döner.
    Eşleşen H kodu yoksa "" (boş) döner.
    """
    if not h_ifadeleri:
        return ""

    en_yuksek_puan = None
    for h in h_ifadeleri:
        kod = h.get("kod", "").strip().upper()
        # "H314+H318" gibi birleşik kodları da ayrıştır
        alt_kodlar = re.findall(r"H\d{3}", kod)
        if not alt_kodlar:
            continue
        for alt_kod in alt_kodlar:
            for grup, puan in H_SIDDET_GRUPLARI:
                if alt_kod in grup:
                    if en_yuksek_puan is None or puan > en_yuksek_puan:
                        en_yuksek_puan = puan

    return en_yuksek_puan if en_yuksek_puan is not None else ""


# ============================================================
# PDF ANALİZ (CAS, İSİM, H/P KODLARI, FİZİKSEL HAL)
# ============================================================

def msds_analiz_ve_cevir(pdf_yolu):
    dosya_adi = os.path.basename(pdf_yolu)
    doc = fitz.open(pdf_yolu)
    tam_metin = ""
    for sayfa in doc:
        tam_metin += sayfa.get_text()
    doc.close()

    temiz_metin = " ".join(tam_metin.split())

    cas_match = re.search(r"CAS[^\d]{0,30}?(\d{2,7}-\d{2}-\d)", temiz_metin, re.IGNORECASE)
    cas_no = cas_match.group(1) if cas_match else "Bulunamadı"

    if cas_no == "Bulunamadı":
        return None

    ad_match = re.search(
        r"(?:Ürün adı|Madde/Müstahzar adı|Kimyasal Adı|Product name)[^\w]*([A-Za-z0-9\-\s\(\)]{3,50}?)(?=\s(?:Product|REACH|CAS|1\.\d))",
        temiz_metin, re.IGNORECASE
    )
    # NOT: ad_match bulunamazsa artık dosya adını DOĞRUDAN kimyasal_adi olarak
    # KULLANMIYORUZ -- bu, "WATER - ULTRA PURE" gibi yanlış eşleşmelerin
    # kaynağıydı. Bulunamazsa kimyasal_adi'ni boş bırakıp ayrı bir
    # "ad_kaynagi" alanıyla işaretliyoruz, böylece hangi kayıtların elle
    # kontrol edilmesi gerektiği açıkça görülür.
    if ad_match:
        kimyasal_adi = ad_match.group(1).strip()
        ad_kaynagi = "pdf_icerigi"
    else:
        kimyasal_adi = dosya_adi.replace(".pdf", "")
        ad_kaynagi = "dosya_adi_yedek"  # <-- gözden geçirilmesi gereken kayıt

    h_kod_pattern = r"\bH\d{3}(?:[A-Za-z]{0,2})?(?:\s*\+\s*H?\d{3}(?:[A-Za-z]{0,2})?)*\b"
    ham_h_kodlari = re.findall(h_kod_pattern, tam_metin)

    # Normalize et: boşlukları temizle, "+" öncesi/sonrası sıkıştır
    h_kod_seti = set()
    for kod in ham_h_kodlari:
        kod_norm = re.sub(r"\s*\+\s*", "+", kod.strip())
        h_kod_seti.add(kod_norm)

    h_listesi = []
    eslesmeyen_h_kodlari = []
    for kod in sorted(h_kod_seti):
        aciklama = h_kodu_aciklama_getir(kod)
        if aciklama is None:
            # Sözlükte karşılığı yok -- muhtemelen yanlış yakalanmış bir kod
            # parçası (örn. "H1" gibi anlamsız bir şey) ya da sözlükte eksik
            # bir varyant. Veritabanına YAZMIYORUZ, sadece loglayıp atlıyoruz.
            eslesmeyen_h_kodlari.append(kod)
            continue
        h_listesi.append({"kod": kod, "aciklama": aciklama})

    # --- P kodları: eski yöntemle (regex + Google Translate) devam ediyor ---
    p_bulunanlar = re.findall(r"(P\d{3}(?:\+P?\d{3})*)\s+([^\n\"]+)", tam_metin)
    p_listesi = [{"kod": k.strip().replace("$", ""), "aciklama": a.strip()} for k, a in p_bulunanlar]
    p_listesi = [dict(t) for t in {tuple(d.items()) for d in p_listesi}]

    # --- Fiziksel hal + olasılık puanı ---
    fiziksel_hal_tr, hal_kategori = fiziksel_hal_coz(tam_metin)
    olasilik_puani = olasilik_puani_hesapla(hal_kategori)

    # H ifadeleri zaten Türkçe (sözlükten geldi) -- çeviriye gerek yok.
    print(f"   🔄 {cas_no} için P kodları Türkçeye çevriliyor...")
    for p in p_listesi:
        try:
            p['aciklama'] = cevirmen.translate(p['aciklama'])
        except Exception:
            pass

    # Şiddet puanı, sözlükten gelen orijinal (eşleşmiş) H kodlarına göre hesaplanır.
    siddet_puani = siddet_puani_hesapla(h_listesi)

    return {
        "kimyasal_adi": kimyasal_adi,
        "ad_kaynagi": ad_kaynagi,
        "cas_no": cas_no,
        "h_ifadeleri": sorted(h_listesi, key=lambda x: x["kod"]),
        "p_ifadeleri": sorted(p_listesi, key=lambda x: x["kod"]),
        "fiziksel_hal": fiziksel_hal_tr,
        "olasilik_puani": olasilik_puani,
        "siddet_puani": siddet_puani,
        "dosya_kaynagi": dosya_adi,
        "_eslesmeyen_h_kodlari": eslesmeyen_h_kodlari,  # sadece konsol logu için, DB'ye yazılmıyor
    }


if __name__ == "__main__":
    koleksiyon = projeyi_baslat()

    print("🧹 Eski veriler temizleniyor...")
    koleksiyon.delete_many({}) 
    print("✨ Veritabanı sıfırlandı!")
    
    if not os.path.exists(KLASOR_ADI):
        os.makedirs(KLASOR_ADI)

    dosyalar = [f for f in os.listdir(KLASOR_ADI) if f.lower().endswith(".pdf")]

    if not dosyalar:
        print(f"⚠️ '{KLASOR_ADI}' klasöründe PDF bulunamadı.")
    else:
        print(f"🚀 Toplam {len(dosyalar)} MSDS taranıyor ve Türkçeye çevriliyor...\n")

        ad_kaynagi_yedek_olanlar = []
        tum_eslesmeyen_h_kodlari = set()

        for dosya in dosyalar:
            tam_yol = os.path.join(KLASOR_ADI, dosya)
            veri = msds_analiz_ve_cevir(tam_yol)

            if veri:
                eslesmeyenler = veri.pop("_eslesmeyen_h_kodlari", [])
                tum_eslesmeyen_h_kodlari.update(eslesmeyenler)

                koleksiyon.update_one({"cas_no": veri["cas_no"]}, {"$set": veri}, upsert=True)
                print(f"✅ Veritabanına Eklendi: {veri['kimyasal_adi']} "
                      f"(CAS: {veri['cas_no']}, Hal: {veri['fiziksel_hal'] or '—'}, "
                      f"Olasılık: {veri['olasilik_puani'] or '—'}, "
                      f"Şiddet: {veri['siddet_puani'] or '—'}, "
                      f"H Kodu Sayısı: {len(veri['h_ifadeleri'])})")
                if veri["ad_kaynagi"] == "dosya_adi_yedek":
                    ad_kaynagi_yedek_olanlar.append(dosya)

        print("\n🎉 İşlem tamamlandı! Veritabanı güncel.")
        if ad_kaynagi_yedek_olanlar:
            print(f"\n⚠️  {len(ad_kaynagi_yedek_olanlar)} dosyada kimyasal adı PDF içeriğinden "
                  f"çekilemedi, dosya adı kullanıldı. Bu kayıtları elle kontrol etmeni öneririm:")
            for d in ad_kaynagi_yedek_olanlar:
                print(f"   - {d}")

        if tum_eslesmeyen_h_kodlari:
            print(f"\n⚠️  Sözlükte karşılığı bulunamayan {len(tum_eslesmeyen_h_kodlari)} kod tespit edildi "
                  f"(muhtemelen yanlış yakalama veya sözlükte eksik varyant). Veritabanına YAZILMADI:")
            for kod in sorted(tum_eslesmeyen_h_kodlari):
                print(f"   - {kod}")
            print("   Bunlar gerçek H kodlarıysa h_kodlari_sozluk.py'ye ekleyebiliriz.")
