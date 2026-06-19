import os
import re
import openpyxl
import joblib
import scipy.sparse as sp
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.model_selection import cross_val_score, StratifiedKFold

KAMUS_NORMALISASI = {
    'btl': 'botol',
    'bks': 'bungkus',
    'sct': 'sachet',
    'sach': 'sachet',
    'gr': 'gram',
    'ml': 'mililiter',
    'pck': 'pack',
    'pak': 'pack',
    'pcs': 'pieces',
    'pc': 'pieces',
    'ind': 'indonesia',
    'tbk': 'terbuka',
    'pt': 'perusahaan',
    'shmp': 'shampoo',
    'shamp': 'shampoo',
    'shampo': 'shampoo',
    'sab': 'sabun',
    'sbn': 'sabun',
    'dtrj': 'deterjen',
    'dtrgen': 'deterjen',
    'kcp': 'kecap',
    'srp': 'sirup',
    'syrup': 'sirup',
    'gndm': 'gandum',
    'mnyk': 'minyak',
    'indomy': 'indomie',
    'chitatoo': 'chitato'
}

def bersihkan_teks(teks):
    teks = str(teks).lower()
    teks = re.sub(r'[^a-z0-9\s]', ' ', teks)
    words = teks.split()
    return ' '.join(KAMUS_NORMALISASI.get(w, w) for w in words)

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    excel_path = os.path.join(base_dir, 'dataset_smart_souvenir.xlsx')
    
    print("Memuat dataset dari:", excel_path)
    if not os.path.exists(excel_path):
        print(f"Error: {excel_path} tidak ditemukan!")
        return
        
    wb = openpyxl.load_workbook(excel_path)
    sheet = wb.active
    rows = list(sheet.iter_rows(values_only=True))
    
    X_raw = []
    y = []
    
    # Skip title and header rows (data starts at index 3)
    for r in rows[3:]:
        nama_produk = r[0]
        perusahaan = r[1] if r[1] is not None else ""
        kategori = r[2]
        
        if nama_produk is not None and kategori is not None:
            teks_gabung = f"{nama_produk} {perusahaan}"
            teks_bersih = bersihkan_teks(teks_gabung)
            X_raw.append(teks_bersih)
            y.append(kategori)
            
    print(f"Total data valid: {len(X_raw)}")
    
    word_vectorizer = TfidfVectorizer(analyzer='word', ngram_range=(1, 2))
    char_vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5))
    
    vectorizer = FeatureUnion([
        ('word', word_vectorizer),
        ('char', char_vectorizer)
    ])
    
    pipeline = Pipeline([
        ('vectorizer', vectorizer),
        ('svc', LinearSVC(random_state=42, C=1.0, dual='auto'))
    ])
    
    print("Mengevaluasi model dengan 5-Fold Cross Validation...")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipeline, X_raw, y, cv=cv, scoring='accuracy')
    print(f"Rata-rata Akurasi Evaluasi: {scores.mean():.4f} (+/- {scores.std():.4f})")
    
    print("Melatih model pada seluruh dataset...")
    pipeline.fit(X_raw, y)
    
    output_model_path = os.path.join(base_dir, 'ml', 'PBL.joblib')
    print(f"Menyimpan model ke {output_model_path}...")
    joblib.dump(pipeline, output_model_path)
    print("Model berhasil diperbarui!")

if __name__ == '__main__':
    main()
