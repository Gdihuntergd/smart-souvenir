/**
 * Kasir Trinity — Core POS & Scanning Script (app.js)
 * Manages the shopping cart, scanning loop, and global helper functions.
 */

// Global state
let cart = [];
let kasirScanning = false;
let kasirScanInterval = null;

// Global settings/constants (synced with python config where needed)
const POINTS_PER_RUPIAH = 1000;

// Helper to format currency
function formatRupiah(num) {
    if (num === undefined || num === null) return '0';
    return Number(num).toLocaleString('id-ID');
}

// Show/Hide Modals
function showModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
        // Specific cleanups on modal close
        if (modalId === 'modal-register') {
            if (typeof stopRegisterCamera === 'function') stopRegisterCamera();
        }
        if (modalId === 'modal-face-verify') {
            if (typeof stopFaceVerifyCamera === 'function') stopFaceVerifyCamera();
        }
        if (modalId === 'modal-member-login') {
            if (typeof stopMemberLoginCamera === 'function') stopMemberLoginCamera();
        }
    }
}

// Initialize Cart on Load
document.addEventListener('DOMContentLoaded', () => {
    syncCartFromDb();
});

// Sync Cart with Backend
async function syncCartFromDb() {
    try {
        const response = await fetch('/kasir/api/cart');
        const data = await response.json();

        if (!data.ok) {
            console.error(data.error || 'Gagal menyinkronkan keranjang');
            return;
        }

        // Map backend rows to frontend item format
        const newCart = data.items.map(row => ({
            id: row.id, // ID primary key in keranjang table
            product_id: row.product_id,
            rfid_tag: row.rfid_tag,
            name: row.nama_produk,
            price: Number(row.harga),
            qty: Number(row.qty),
            emoji: 'shopping-bag'
        }));

        // Check if cart has changed
        const cartChanged = JSON.stringify(cart) !== JSON.stringify(newCart);
        if (cartChanged) {
            cart = newCart;
            renderScannedProducts();
            updateCart();
        }
    } catch (error) {
        console.error('Error syncing cart:', error);
    }
}

// Render Products in Scanned Products Area
function renderScannedProducts() {
    const container = document.getElementById('scanned-products');
    if (!container) return;

    if (cart.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = `
        <h3 style="display:flex;align-items:center;gap:8px;"><i data-lucide="package" style="width:20px;height:20px;"></i> Produk yang Discan</h3>
        ${cart.map(item => `
            <div class="scanned-item" data-id="${item.id}">
                <div class="item-details-scan">
                    <div class="item-emoji" style="display:flex;align-items:center;justify-content:center;"><i data-lucide="${item.emoji}" style="width:28px;height:28px;color:var(--primary);"></i></div>
                    <div class="item-info-scan">
                        <div class="item-name-scan">${item.name}</div>
                        <div class="item-price-scan">Rp ${formatRupiah(item.price)}</div>
                    </div>
                </div>
                <div class="item-controls">
                    <button class="btn-delete-item" onclick="removeScannedProduct('${item.id}')" style="display:flex;align-items:center;gap:4px;">
                        <i data-lucide="trash-2" style="width:14px;height:14px;"></i> Hapus
                    </button>
                </div>
            </div>
        `).join('')}
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Update Cart Area and Subtotal/Total Displays
function updateCart() {
    const cartItems = document.getElementById('cart-items');
    const cartTotal = document.getElementById('cart-total');
    const payBtn = document.getElementById('pay-btn');

    if (!cartItems || !cartTotal || !payBtn) return;

    if (cart.length === 0) {
        cartItems.innerHTML = `
            <div class="cart-empty">
                <div class="empty-icon" style="display:flex;justify-content:center;align-items:center;color:var(--text-muted);"><i data-lucide="shopping-cart" style="width:48px;height:48px;"></i></div>
                <p>Keranjang masih kosong</p>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        cartTotal.classList.add('hidden');
        payBtn.disabled = true;
    } else {
        cartItems.innerHTML = cart.map(item => `
            <div class="cart-item">
                <div class="item-info">
                    <div class="item-name"><i data-lucide="${item.emoji}" style="width:14px;height:14px;display:inline-block;vertical-align:middle;margin-right:4px;color:var(--primary);"></i>${item.name}</div>
                    <div class="item-details">${item.qty} x Rp ${formatRupiah(item.price)}</div>
                </div>
                <div class="item-total">Rp ${formatRupiah(item.price * item.qty)}</div>
            </div>
        `).join('');

        const subtotal = cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
        
        // Check if points are redeemed (from global payment state)
        const pointsUsed = typeof redeemPointsUsed !== 'undefined' ? redeemPointsUsed : 0;
        const finalTotal = Math.max(0, subtotal - pointsUsed);

        const subtotalEl = document.getElementById('subtotal');
        const totalEl = document.getElementById('total');

        if (subtotalEl) subtotalEl.textContent = `Rp ${formatRupiah(subtotal)}`;
        if (totalEl) totalEl.textContent = `Rp ${formatRupiah(finalTotal)}`;

        // Handle points discount row in Cart Total
        let discountRow = document.getElementById('cart-discount-row');
        if (pointsUsed > 0) {
            if (!discountRow) {
                discountRow = document.createElement('div');
                discountRow.id = 'cart-discount-row';
                discountRow.className = 'total-row discount';
                cartTotal.insertBefore(discountRow, document.querySelector('.total-final'));
            }
            discountRow.innerHTML = `
                <span>Redeem Point:</span>
                <span>- Rp ${formatRupiah(pointsUsed)}</span>
            `;
        } else if (discountRow) {
            discountRow.remove();
        }

        cartTotal.classList.remove('hidden');
        payBtn.disabled = false;
    }
}

// Remove Scanned Product by Database ID
async function removeScannedProduct(id) {
    // Optimistic UI update
    cart = cart.filter(item => String(item.id) !== String(id));
    renderScannedProducts();
    updateCart();

    try {
        const response = await fetch('/kasir/api/cart/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: id })
        });
        
        const data = await response.json();
        if (!data.ok) {
            console.error(data.error || 'Gagal menghapus item dari server');
            // Re-sync to restore correct state in case of error
            syncCartFromDb();
        }
    } catch (error) {
        console.error('Error deleting product:', error);
        syncCartFromDb();
    }
}

// Toggle RFID barcode scanning simulation (polling)
async function toggleScanner() {
    kasirScanning = !kasirScanning;
    
    const scannerBox = document.getElementById('scanner-box');
    const toggleBtn = document.getElementById('scan-toggle-btn');
    
    if (!scannerBox || !toggleBtn) return;

    if (kasirScanning) {
        // Start scanning
        scannerBox.classList.add('scanning');
        scannerBox.style.background = 'rgba(0, 200, 83, 0.05)';
        scannerBox.style.borderColor = 'var(--success)';
        toggleBtn.innerHTML = '<i data-lucide="square" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Stop Scan Produk';
        toggleBtn.className = 'btn btn-danger mt-2';
        _refreshIcons();

        // Perform initial sync and start polling interval
        await syncCartFromDb();
        kasirScanInterval = setInterval(syncCartFromDb, 800);
    } else {
        // Stop scanning
        stopScannerUI();
    }
}

function stopScannerUI() {
    kasirScanning = false;
    if (kasirScanInterval) {
        clearInterval(kasirScanInterval);
        kasirScanInterval = null;
    }

    const scannerBox = document.getElementById('scanner-box');
    const toggleBtn = document.getElementById('scan-toggle-btn');
    
    if (scannerBox) {
        scannerBox.classList.remove('scanning');
        scannerBox.style.background = '';
        scannerBox.style.borderColor = '';
    }
    if (toggleBtn) {
        toggleBtn.innerHTML = '<i data-lucide="search" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Mulai Scan Produk';
        toggleBtn.className = 'btn btn-outline mt-2';
    }
}

// Re-initialize lucide icons after dynamic content
function _refreshIcons() {
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Simulate RFID barcode scan using real available item from database
async function simulateScan() {
    const simulateBtn = document.getElementById('scan-simulate-btn');
    if (simulateBtn) simulateBtn.disabled = true;

    try {
        const response = await fetch('/kasir/api/scan_rfid/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (!data.ok) {
            alert(data.error || 'Gagal mensimulasikan scan barang');
            return;
        }

        // Show scanner box blink success feedback (matches scanning feedback)
        const scannerBox = document.getElementById('scanner-box');
        if (scannerBox) {
            const originalBg = scannerBox.style.background;
            const originalBorder = scannerBox.style.borderColor;
            
            scannerBox.style.background = 'rgba(0, 200, 83, 0.1)';
            scannerBox.style.borderColor = 'var(--success)';
            
            setTimeout(() => {
                scannerBox.style.background = originalBg;
                scannerBox.style.borderColor = originalBorder;
            }, 600);
        }

        // Trigger immediate sync to show the new item in scanned list & cart
        await syncCartFromDb();
        
    } catch (error) {
        console.error('Simulate scan error:', error);
        alert('Gagal menghubungi server untuk simulasi scan.');
    } finally {
        if (simulateBtn) simulateBtn.disabled = false;
    }
}
