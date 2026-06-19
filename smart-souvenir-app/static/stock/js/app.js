console.log('app.js init');

function initApp() {
  // =========================
  // 1. PENCARIAN & FILTER TANPA DATATABLE
  // =========================
  const table          = document.getElementById('productTable');
  const searchBox      = document.getElementById('searchBox');
  const filterCategory = document.getElementById('filterCategory');
  const filterStatus   = document.getElementById('filterStatus');

  function applyFilters() {
    if (!table) return;
    const term = (searchBox && searchBox.value || '').toLowerCase();
    const cat  = (filterCategory && filterCategory.value) || '';
    const stat = (filterStatus && filterStatus.value) || '';

    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(tr => {
      const rowCat  = tr.dataset.category || '';
      const rowStat = tr.dataset.status || '';
      const text    = tr.textContent.toLowerCase();

      const okCat    = !cat  || rowCat === cat;
      const okStat   = !stat || rowStat === stat;
      const okSearch = !term || text.includes(term);

      const isVisible = okCat && okStat && okSearch;
      tr.style.display = isVisible ? '' : 'none';

      if (!isVisible) {
        const cb = tr.querySelector('.product-checkbox');
        if (cb) cb.checked = false;
      }
    });

    if (typeof updateDeleteSelectedButton === 'function') {
      updateDeleteSelectedButton();
    }
  }

  if (searchBox) {
    searchBox.addEventListener('keyup', applyFilters);
  }
  if (filterCategory) {
    filterCategory.addEventListener('change', applyFilters);
  }
  if (filterStatus) {
    filterStatus.addEventListener('change', applyFilters);
  }

  // =========================
  // 2. MODAL DETAIL PRODUK ("Lihat")
  // =========================
  document.querySelectorAll('.btn-detail').forEach(btn => {
    btn.addEventListener('click', async () => {
      const id = btn.dataset.id;
      if (!id) return;

      try {
        const res  = await fetch('product_detail.php?id=' + encodeURIComponent(id));
        const data = await res.json();
        console.log('detail data:', data);

        const titleEl   = document.getElementById('detailTitle');
        const summaryEl = document.getElementById('detailSummary');
        const tbody     = document.querySelector('#detailTable tbody');

        if (titleEl) {
          titleEl.textContent = data.name || '-';
        }

        if (summaryEl && data.summary) {
          const box = (label, val) => `
            <div class="col">
              <div class="detail-summary-card">
                <div class="small text-secondary fw-semibold mb-1">${label}</div>
                <div class="h5 mb-0 fw-bold text-dark">${val} unit</div>
              </div>
            </div>`;
          summaryEl.innerHTML =
            box('Tersedia',    data.summary.tersedia ?? 0) +
            box('Dipesan',     data.summary.dipesan ?? 0) +
            box('Terjual',     data.summary.terjual ?? 0);
        }

        if (tbody) {
          tbody.innerHTML = '';
          (data.items || []).forEach(it => {
            tbody.insertAdjacentHTML('beforeend', `
              <tr>
                <td>${it.item_code || ''}</td>
                <td>${it.condition || ''}</td>
                <td>${it.status || ''}</td>
                <td>${it.purchase_date || ''}</td>
                <td>
                  <button type="button"
                          class="btn btn-sm btn-outline-danger btn-delete-item"
                          data-id="${it.id}">
                    Hapus
                  </button>
                </td>
              </tr>
            `);
          });
        }

        const modalEl = document.getElementById('detailModal');
        if (modalEl && window.bootstrap) {
          const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
          modal.show();
        }
      } catch (err) {
        console.error('Gagal ambil detail produk:', err);
        alert('Gagal memuat detail produk.');
      }
    });
  });

  // =========================
  // 3. TOMBOL HAPUS ITEM DI MODAL DETAIL
  // =========================
  const detailModalEl = document.getElementById('detailModal');

  if (detailModalEl) {
    detailModalEl.addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-delete-item');
      if (!btn) return; // klik bukan tombol Hapus

      const itemId = btn.dataset.id;
      if (!itemId) return;

      if (!confirm('Yakin ingin menghapus item ini?')) return;

      fetch('item_delete.php', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: 'id=' + encodeURIComponent(itemId),
      })
      .then(r => r.json())
      .then(res => {
        if (res && res.success) {
          const row = btn.closest('tr');
          if (row) row.remove();
        } else {
          alert(res.message || 'Gagal menghapus item');
        }
      })
      .catch(() => {
        alert('Terjadi kesalahan saat menghapus item');
      });
    });
  }

  // =========================
  // 4. TOMBOL RESTOCK (SET PRODUK TERPILIH)
  // =========================
  document.querySelectorAll('.btn-restock').forEach(btn => {
    btn.addEventListener('click', () => {
      const id  = btn.dataset.id;
      const sel = document.getElementById('restockProduct');
      if (sel && id) {
        sel.value = id;
      }

      const modalEl = document.getElementById('restockModal');
      if (modalEl && window.bootstrap) {
        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
        modal.show();
      }
    });
  });

  // =========================
  // 5. LIVE SCAN RFID -> TEXTAREA (DIBATASI KUANTITAS)
  // =========================
  const btnScan   = document.getElementById('btnStartScan');
  const area      = document.getElementById('rfidTags');
  const qtyInput  = document.querySelector('input[name="qty"]');

  let isScanning   = false;
  let scanInterval = null;

  function getExistingTags() {
    return (area && area.value || '')
      .split(/\r?\n/)
      .map(s => s.trim())
      .filter(Boolean);
  }

  function setScanButtonState() {
    if (!btnScan) return;
    btnScan.textContent = isScanning ? 'Stop Scan RFID' : 'Mulai Scan RFID';
  }

  function stopScan() {
    if (!isScanning) return;
    isScanning = false;
    if (scanInterval) {
      clearInterval(scanInterval);
      scanInterval = null;
    }
    if (btnScan) btnScan.disabled = false;
    setScanButtonState();
    console.log('Scan RFID dihentikan');
  }

  async function pollRfidOnce() {
    if (!isScanning || !area) return;

    const qtyMax = parseInt(qtyInput && qtyInput.value, 10) || 0;
    if (!qtyMax || qtyMax <= 0) {
      alert('Isi kolom Kuantitas terlebih dahulu (minimal 1) sebelum scan RFID.');
      stopScan();
      return;
    }

    let existing = getExistingTags();

    // Kalau sudah penuh, stop scanning
    if (existing.length >= qtyMax) {
      alert(`Tag RFID sudah mencapai batas kuantitas (${qtyMax}).`);
      stopScan();
      return;
    }

    const remaining = qtyMax - existing.length;

    try {
      const res  = await fetch('api/rfid_push.php?limit=' + remaining);
      const data = await res.json();
      console.log('rfid_push data (live):', data);

      if (!data.ok) {
        console.error('Error dari rfid_push:', data.error);
        return;
      }

      if (!data.tags || data.tags.length === 0) {
        // tidak ada tag baru di inbox
        return;
      }

      data.tags.forEach(tag => {
        if (existing.length >= qtyMax) return; // jaga-jaga
        tag = String(tag).trim();
        if (!tag) return;
        if (!existing.includes(tag)) {
          existing.push(tag);
        }
      });

      area.value = existing.join('\n');

      if (existing.length >= qtyMax) {
        alert(`Tag RFID sudah mencapai batas kuantitas (${qtyMax}).`);
        stopScan();
      }
    } catch (err) {
      console.error('Error ambil RFID:', err);
      stopScan();
    }
  }

  function startScan() {
    if (!btnScan || !area) return;

    const qtyMax = parseInt(qtyInput && qtyInput.value, 10) || 0;
    if (!qtyMax || qtyMax <= 0) {
      alert('Isi kolom Kuantitas terlebih dahulu (minimal 1) sebelum scan RFID.');
      return;
    }

    let existing = getExistingTags();
    if (existing.length >= qtyMax) {
      alert(`Tag RFID sudah sudah mencapai batas kuantitas (${qtyMax}). Hapus beberapa dulu jika mau scan ulang.`);
      return;
    }

    isScanning = true;
    setScanButtonState();
    btnScan.disabled = false; // tetap bisa dipencet untuk stop

    console.log('Scan RFID dimulai');

    // polling pertama langsung
    pollRfidOnce();
    // lalu polling berkala
    scanInterval = setInterval(pollRfidOnce, 700);
  }

  if (btnScan && area) {
    setScanButtonState();
    btnScan.addEventListener('click', () => {
      if (isScanning) {
        stopScan();
      } else {
        startScan();
      }
    });
  }

  // =========================
  // 6. BERSIHKAN rfid_inbox & HENTIKAN SCAN SAAT MODAL RESTOCK DITUTUP
  // =========================
  const restockModalEl = document.getElementById('restockModal');
  if (restockModalEl && window.bootstrap) {
    restockModalEl.addEventListener('hidden.bs.modal', () => {
      // stop live scan
      stopScan();

      // kosongkan textarea & reset kuantitas (opsional)
      if (area) area.value = '';
      if (qtyInput) qtyInput.value = '1';

      // panggil API clear inbox di server
      fetch('api/rfid_clear.php')
        .then(res => res.json())
        .then(data => {
          console.log('rfid_clear:', data);
        })
        .catch(err => {
          console.error('Gagal clear rfid_inbox:', err);
        });
    });
  }

  // =========================
  // 7. SELEKSI MASSAL & HAPUS MASAL (BULK DELETE)
  // =========================
  const selectAllCb      = document.getElementById('selectAllProducts');
  const deleteSelectedBtn = document.getElementById('btnDeleteSelected');
  const deleteCountEl     = document.getElementById('deleteCount');
  const bulkDeleteModalEl = document.getElementById('bulkDeleteModal');
  const bulkDeleteIdsInput = document.getElementById('bulkDeleteIdsInput');
  const bulkDeleteCountText = document.getElementById('bulkDeleteCountText');

  function updateDeleteSelectedButton() {
    if (!table || !deleteSelectedBtn || !deleteCountEl) return;
    const checkedCbs = table.querySelectorAll('tbody tr .product-checkbox:checked');
    const count = checkedCbs.length;

    if (count > 0) {
      deleteCountEl.textContent = count;
      deleteSelectedBtn.classList.remove('d-none');
      deleteSelectedBtn.classList.add('d-flex');
    } else {
      deleteSelectedBtn.classList.remove('d-flex');
      deleteSelectedBtn.classList.add('d-none');
      if (selectAllCb) selectAllCb.checked = false;
    }
  }

  if (selectAllCb && table) {
    selectAllCb.addEventListener('change', () => {
      const isChecked = selectAllCb.checked;
      const visibleRows = table.querySelectorAll('tbody tr');
      visibleRows.forEach(tr => {
        if (tr.style.display !== 'none') {
          const cb = tr.querySelector('.product-checkbox');
          if (cb) cb.checked = isChecked;
        }
      });
      updateDeleteSelectedButton();
    });
  }

  if (table) {
    table.querySelector('tbody')?.addEventListener('change', (e) => {
      if (e.target && e.target.classList.contains('product-checkbox')) {
        updateDeleteSelectedButton();

        // Update selectAll checkbox state
        if (selectAllCb) {
          const visibleRows = Array.from(table.querySelectorAll('tbody tr')).filter(tr => tr.style.display !== 'none');
          const visibleCbs = visibleRows.map(tr => tr.querySelector('.product-checkbox')).filter(Boolean);
          const allChecked = visibleCbs.length > 0 && visibleCbs.every(cb => cb.checked);
          selectAllCb.checked = allChecked;
        }
      }
    });
  }

  if (deleteSelectedBtn && bulkDeleteModalEl && bulkDeleteIdsInput && bulkDeleteCountText && window.bootstrap) {
    deleteSelectedBtn.addEventListener('click', () => {
      const checkedCbs = table.querySelectorAll('tbody tr .product-checkbox:checked');
      const ids = Array.from(checkedCbs).map(cb => cb.value);

      bulkDeleteIdsInput.value = ids.join(',');
      bulkDeleteCountText.textContent = ids.length;

      const modal = bootstrap.Modal.getOrCreateInstance(bulkDeleteModalEl);
      modal.show();
    });
  }
}

// DOM sudah siap karena script diletakkan di akhir body
initApp();

const addProductForm = document.getElementById('addProductForm');
const productNameInput = document.getElementById('productNameInput');
const categorySelect = document.getElementById('categorySelect');
const predictionBox = document.getElementById('predictionBox');
const predictionText = document.getElementById('predictionText');

let categoryPredicted = false;

if (addProductForm && productNameInput && categorySelect && predictionBox && predictionText) {
  addProductForm.addEventListener('keydown', async function (event) {
    if (event.key !== 'Enter') {
      return;
    }

    if (!categoryPredicted) {
      event.preventDefault();

      const productName = productNameInput.value.trim();

      if (!productName) {
        predictionText.textContent = 'Nama produk belum diisi';
        predictionBox.classList.remove('d-none');
        return;
      }

      const formData = new FormData();
      formData.append('name', productName);
      const supplierSelect = addProductForm.querySelector('[name="supplier_id"]');
      const supplierName = supplierSelect?.selectedOptions[0]?.dataset.name || '';
      formData.append('supplier', supplierName);

      try {
        const response = await fetch('api/predict_category.php', {
          method: 'POST',
          body: formData
        });

        const result = await response.json();

        if (result.ok) {
          categorySelect.value = result.category_id;
          predictionText.textContent = result.category_name;
          predictionBox.classList.remove('d-none');
          categoryPredicted = true;
        } else {
          predictionText.textContent = result.message || 'Prediksi gagal';
          predictionBox.classList.remove('d-none');
        }
      } catch (error) {
        predictionText.textContent = 'Prediksi gagal diproses';
        predictionBox.classList.remove('d-none');
      }

      return;
    }

    addProductForm.submit();
  });

  productNameInput.addEventListener('input', function () {
    categoryPredicted = false;
    predictionBox.classList.add('d-none');
    predictionText.textContent = '';
  });

  categorySelect.addEventListener('change', function () {
    categoryPredicted = true;
    predictionBox.classList.add('d-none');
  });
}

// =========================
// 8. DATA SUPPLIER MODAL (ENKRIPSI → DEKRIPSI)
// =========================
const btnViewSuppliers = document.getElementById('btnViewSuppliers');
const supplierModal = document.getElementById('supplierModal');

let supplierData = null;  // Cache the fetched data
let isDecrypted = false;  // Current view state

if (btnViewSuppliers && supplierModal) {
  const btnToggleDecrypt = document.getElementById('btnToggleDecrypt');
  const supplierViewMode = document.getElementById('supplierViewMode');
  const avgEncryptCardWrapper = document.getElementById('avgEncryptCardWrapper');
  const avgDecryptCardWrapper = document.getElementById('avgDecryptCardWrapper');
  const encryptionInfo = document.getElementById('encryptionInfo');
  const supplierTableHeader = document.getElementById('supplierTableHeader');
  const supplierTableBody = document.getElementById('supplierTableBody');

  // Reset state when modal opens
  supplierModal.addEventListener('show.bs.modal', () => {
    isDecrypted = false;
    supplierData = null;
  });

  // Toggle button click
  if (btnToggleDecrypt) {
    btnToggleDecrypt.addEventListener('click', async () => {
      if (!isDecrypted) {
        await decryptData();
      } else {
        isDecrypted = false;
        updateViewState();
      }
    });
  }

  // Main button click - show modal with encrypted data
  btnViewSuppliers.addEventListener('click', async () => {
    const modal = bootstrap.Modal.getOrCreateInstance(supplierModal);
    modal.show();
    await loadEncryptedData();
  });

  async function loadEncryptedData() {
    if (supplierTableBody) {
      supplierTableBody.innerHTML = `
        <tr>
          <td colspan="5" class="text-center py-5">
            <div class="spinner-border text-primary" role="status" style="width: 3rem; height: 3rem;">
              <span class="visually-hidden">Loading...</span>
            </div>
            <p class="mt-3 mb-0 text-secondary fw-semibold">Memuat data supplier...</p>
          </td>
        </tr>
      `;
    }

    try {
      const res = await fetch('api/suppliers_decrypted.php');
      const data = await res.json();

      if (!data.ok) {
        throw new Error(data.message || 'Gagal memuat data supplier');
      }

      supplierData = data;
      isDecrypted = false;
      updateViewState();
    } catch (err) {
      console.error('Gagal memuat data supplier:', err);
      if (supplierTableBody) {
        supplierTableBody.innerHTML = `
          <tr>
            <td colspan="5" class="text-center py-5 text-danger">
              <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>
              <p class="mt-2 mb-0 fw-semibold">${escapeHtml(err.message)}</p>
            </td>
          </tr>
        `;
      }
    }
  }

  async function decryptData() {
    if (!supplierData) return;

    if (supplierTableBody) {
      supplierTableBody.innerHTML = `
        <tr>
          <td colspan="5" class="text-center py-5">
            <div class="spinner-border" role="status" style="width: 3rem; height: 3rem; color: #f5576c;">
              <span class="visually-hidden">Decrypting...</span>
            </div>
            <p class="mt-3 mb-0 text-secondary fw-semibold">Mendekripsi data dengan AES-256...</p>
          </td>
        </tr>
      `;
    }

    await new Promise(r => setTimeout(r, 500));

    isDecrypted = true;
    updateViewState();
  }

  function updateViewState() {
    if (!supplierData || !supplierData.suppliers) return;

    // Update badge
    if (supplierViewMode) {
      supplierViewMode.textContent = isDecrypted ? 'Dekripsi' : 'Terenkripsi';
      supplierViewMode.className = isDecrypted 
        ? 'badge bg-success ms-2' 
        : 'badge bg-white text-dark ms-2';
      supplierViewMode.style.fontSize = '11px';
    }

    // Update total supplier card value
    document.getElementById('statTotalSupplierMain').textContent = supplierData.total_suppliers || 0;

    // Show/hide encrypt/decrypt stats cards
    if (avgEncryptCardWrapper) {
      avgEncryptCardWrapper.classList.toggle('d-none', !isDecrypted);
    }
    if (avgDecryptCardWrapper) {
      avgDecryptCardWrapper.classList.toggle('d-none', !isDecrypted);
    }
    if (encryptionInfo) {
      encryptionInfo.classList.toggle('d-none', !isDecrypted);
    }

    // Update stats values
    if (isDecrypted) {
      document.getElementById('statAvgEncrypt').textContent = (supplierData.avg_encrypt_time_ms || 0) + ' ms';
      document.getElementById('statAvgDecrypt').textContent = (supplierData.avg_decrypt_time_ms || 0) + ' ms';
    }

    // Update table header
    if (supplierTableHeader) {
      if (isDecrypted) {
        supplierTableHeader.innerHTML = `
          <th class="ps-3" style="width: 60px;">ID</th>
          <th>Nama</th>
          <th>Alamat <span class="badge bg-success" style="font-size: 10px;">Asli</span></th>
          <th>No. HP</th>
          <th>Email <span class="badge bg-success" style="font-size: 10px;">Asli</span></th>
          <th class="text-center">Waktu Enkripsi</th>
          <th class="text-center">Waktu Dekripsi</th>
        `;
      } else {
        supplierTableHeader.innerHTML = `
          <th class="ps-3" style="width: 60px;">ID</th>
          <th>Nama</th>
          <th>Alamat <span class="badge bg-secondary" style="font-size: 10px;">Terenkripsi</span></th>
          <th>No. HP</th>
          <th>Email <span class="badge bg-secondary" style="font-size: 10px;">Terenkripsi</span></th>
        `;
      }
    }

    // Update table body
    if (supplierTableBody) {
      supplierTableBody.innerHTML = '';

      if (supplierData.suppliers.length > 0) {
        supplierData.suppliers.forEach(s => {
          if (isDecrypted) {
            const encryptBadge = getSpeedBadge(s.encrypt_time_ms);
            const decryptBadge = getSpeedBadge(s.decrypt_time_ms);
            supplierTableBody.insertAdjacentHTML('beforeend', `
              <tr>
                <td class="ps-3 fw-medium">${s.id}</td>
                <td class="fw-semibold">${escapeHtml(s.nama)}</td>
                <td>${escapeHtml(s.alamat_decrypted || '-')}</td>
                <td class="fw-medium">${escapeHtml(s.hp_decrypted || '-')}</td>
                <td>${escapeHtml(s.email_decrypted || '-')}</td>
                <td class="text-center">${encryptBadge}</td>
                <td class="text-center">${decryptBadge}</td>
              </tr>
            `);
          } else {
            supplierTableBody.insertAdjacentHTML('beforeend', `
              <tr>
                <td class="ps-3 fw-medium">${s.id}</td>
                <td class="fw-semibold">${escapeHtml(s.nama)}</td>
                <td><code class="small text-muted" style="font-size: 11px;">${escapeHtml(s.alamat_encrypted || '-')}</code></td>
                <td class="fw-medium">${escapeHtml(s.hp_encrypted || '-')}</td>
                <td><code class="small text-muted" style="font-size: 11px;">${escapeHtml(s.email_encrypted || '-')}</code></td>
              </tr>
            `);
          }
        });
      } else {
        const colSpan = isDecrypted ? 7 : 5;
        supplierTableBody.innerHTML = `
          <tr>
            <td colspan="${colSpan}" class="text-center py-5 text-secondary">
              <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg>
              <p class="mt-2 mb-0 fw-semibold">Tidak ada data supplier.</p>
            </td>
          </tr>
        `;
      }
    }

    // Update toggle button
    if (btnToggleDecrypt) {
      if (isDecrypted) {
        btnToggleDecrypt.innerHTML = `
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
          Sembunyikan Data Asli
        `;
        btnToggleDecrypt.style.background = '#6c757d';
      } else {
        btnToggleDecrypt.innerHTML = `
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
          Perlihatkan Data Asli
        `;
        btnToggleDecrypt.style.background = 'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)';
      }
    }
  }
}

// Helper function to get speed badge based on time
function getSpeedBadge(timeMs) {
  let badgeClass = 'bg-success';
  let label = 'Sangat Cepat';
  
  if (timeMs > 10) {
    badgeClass = 'bg-warning text-dark';
    label = 'Cepat';
  } else if (timeMs > 5) {
    badgeClass = 'bg-info';
    label = 'Normal';
  }
  
  return `<span class="badge ${badgeClass}">${timeMs} ms</span> <small class="text-secondary d-block">${label}</small>`;
}

// Helper function to escape HTML
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}