/**
 * Kasir Trinity — Payment Flow Script (payment.js)
 * Coordinates the checkout process, points calculations, QRIS payments, and success dialogs.
 */

// Global payment states
let paymentMode = 'regular'; // 'regular' | 'redeem'
let redeemPointsUsed = 0;
let qrPaymentType = 'nonmember'; // 'member' | 'nonmember'

// Open checkout selection
function openPaymentChoice() {
    // Stop barcode/RFID scanner polling while paying
    if (typeof stopScannerUI === 'function') {
        stopScannerUI();
    }
    
    // Default reset states
    paymentMode = 'regular';
    redeemPointsUsed = 0;
    
    showModal('modal-payment-choice');
}

// Option chosen: Pay as Member
function chooseMemberPayment() {
    closeModal('modal-payment-choice');
    if (typeof startMemberLoginFlow === 'function') {
        startMemberLoginFlow();
    } else {
        showModal('modal-member-login');
    }
}

// Option chosen: Pay as Non-Member
function chooseNonMemberPayment() {
    closeModal('modal-payment-choice');
    showModal('modal-nonmember');
}

// Change member point option (Regular vs Redeem Points)
function selectPointOption(option) {
    paymentMode = option;

    const optRegular = document.getElementById('opt-regular');
    const optRedeem = document.getElementById('opt-redeem');

    if (optRegular && optRedeem) {
        if (option === 'redeem') {
            optRegular.classList.remove('selected');
            optRedeem.classList.add('selected');
        } else {
            optRegular.classList.add('selected');
            optRedeem.classList.remove('selected');
        }
    }

    updatePaymentOptions();
}

// Recalculate points redeemable based on current cart
function updatePaymentOptions() {
    if (!activeMember) return;

    const subtotal = cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
    const maxRedeemable = Math.min(activeMember.points, subtotal);

    const redeemInfo = document.getElementById('redeem-info');
    const redeemText = document.getElementById('redeem-info-text');

    if (paymentMode === 'redeem') {
        redeemPointsUsed = maxRedeemable;
        if (redeemText) {
            redeemText.textContent = `Menggunakan ${formatRupiah(redeemPointsUsed)} poin untuk mendapatkan potongan harga Rp ${formatRupiah(redeemPointsUsed)}.`;
        }
        if (redeemInfo) redeemInfo.classList.remove('hidden');
    } else {
        redeemPointsUsed = 0;
        if (redeemInfo) redeemInfo.classList.add('hidden');
    }

    // Refresh core cart summary totals
    if (typeof updateCart === 'function') {
        updateCart();
    }
}

// Face Pay Verification Flow
function startFacePayment() {
    if (!activeMember) return;

    // Member yang login via face recognition sudah terbukti memiliki wajah terdaftar
    // Jadi langsung izinkan Face Pay tanpa pengecekan ulang
    if (!activeMember.has_face) {
        // Double check: query server apakah member punya face enrollment
        fetch(`/kasir/api/member/lookup?phone=${encodeURIComponent(activeMember.phone || '')}`)
            .then(r => r.json())
            .then(data => {
                if (data.ok && data.member && data.member.has_face) {
                    activeMember.has_face = true;
                    startFacePayment(); // retry
                } else {
                    alert('Maaf, member ini belum mendaftarkan wajah. Silakan daftarkan wajah terlebih dahulu melalui menu pendaftaran member.');
                }
            })
            .catch(() => {
                // Fallback: allow face pay anyway since member logged in via face
                proceedFacePayment();
            });
        return;
    }

    proceedFacePayment();
}

function proceedFacePayment() {

    closeModal('modal-member-dashboard');
    showModal('modal-face-verify');
    
    // Start video capture stream
    if (typeof startFaceVerifyCamera === 'function') {
        startFaceVerifyCamera();
    }
}

// QRIS Payment Modal Init
function startQRPayment(type) {
    qrPaymentType = type;

    // Close source overlays
    if (type === 'member') {
        closeModal('modal-member-dashboard');
    } else {
        closeModal('modal-nonmember');
    }

    showModal('modal-qr-payment');

    // Calculations
    const subtotal = cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
    const redeemPoints = (type === 'member' && paymentMode === 'redeem') ? redeemPointsUsed : 0;
    const finalTotal = Math.max(0, subtotal - redeemPoints);
    const earnedPoints = Math.floor(finalTotal / POINTS_PER_RUPIAH);

    // Update displays
    const totalDisplay = document.getElementById('qr-total-display');
    if (totalDisplay) totalDisplay.textContent = `Rp ${formatRupiah(finalTotal)}`;

    const pointInfo = document.getElementById('qr-point-info');
    const pointText = document.getElementById('qr-point-info-text');

    if (type === 'member' && pointInfo && pointText) {
        pointText.innerHTML = `<i data-lucide="gift" style="width:16px;height:16px;display:inline;vertical-align:middle;margin-right:4px;"></i> Selamat! Anda akan mendapatkan +${earnedPoints} poin dari transaksi ini.`;
        pointInfo.classList.remove('hidden');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } else if (pointInfo) {
        pointInfo.classList.add('hidden');
    }

    // Generate dynamic QRIS code
    const qrWrapper = document.getElementById('qr-code-display');
    if (qrWrapper) {
        qrWrapper.innerHTML = '';
        new QRCode(qrWrapper, {
            text: `TRINITY-QRIS-${finalTotal}-${Date.now()}`,
            width: 200,
            height: 200,
            colorDark: "#1a1a2e",
            colorLight: "#ffffff",
            correctLevel: QRCode.CorrectLevel.M
        });
    }
}

// Confirm QRIS Payment API Call
async function confirmQRPayment() {
    const confirmBtn = document.querySelector('#modal-qr-payment button[onclick="confirmQRPayment()"]');
    const textSpan = document.getElementById('qr-confirm-text');
    const spinner = document.getElementById('qr-confirm-spinner');

    if (confirmBtn) confirmBtn.disabled = true;
    if (textSpan) textSpan.classList.add('hidden');
    if (spinner) spinner.classList.remove('hidden');

    const subtotal = cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
    const isMember = (qrPaymentType === 'member');
    const redeemPoints = (isMember && paymentMode === 'redeem') ? redeemPointsUsed : 0;
    const finalTotal = Math.max(0, subtotal - redeemPoints);
    const earnedPoints = Math.floor(finalTotal / POINTS_PER_RUPIAH);

    const cartPayload = cart.map(item => ({
        product_id: item.product_id,
        quantity: item.qty,
        price: item.price,
        rfid_tag: item.rfid_tag
    }));

    try {
        const response = await fetch('/kasir/api/payment/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                cart: cartPayload,
                subtotal: subtotal,
                final_total: finalTotal,
                is_member: isMember,
                phone: isMember ? activeMember.phone : '',
                payment_mode: isMember ? paymentMode : 'regular',
                redeem_points: redeemPoints,
                earned_points: earnedPoints
            })
        });

        const data = await response.json();

        if (!data.ok) {
            alert(data.error || 'Pembayaran gagal diproses.');
            return;
        }

        // Close QR payment modal
        closeModal('modal-qr-payment');

        // Show transaction receipt modal
        showSuccessScreen({
            id_transaksi: data.id_transaksi,
            payment_method: 'Scan QR (QRIS)',
            subtotal: subtotal,
            points_redeemed: redeemPoints,
            final_total: finalTotal,
            is_member: isMember,
            member_name: isMember ? activeMember.name : null,
            new_saldo: isMember ? activeMember.saldo : null,
            new_points: isMember ? (activeMember.points - redeemPoints + earnedPoints) : null
        });

    } catch (error) {
        console.error('QRIS payment process error:', error);
        alert('Kesalahan jaringan. Pembayaran gagal.');
    } finally {
        if (confirmBtn) confirmBtn.disabled = false;
        if (textSpan) textSpan.classList.remove('hidden');
        if (spinner) spinner.classList.add('hidden');
    }
}

// Show transaction success screen
function showSuccessScreen(details) {
    const txnIdEl = document.getElementById('success-txn-id');
    const receiptBox = document.getElementById('success-receipt');
    const memberInfoDiv = document.getElementById('success-member-info');
    const pointsMsgEl = document.getElementById('success-points-msg');

    if (txnIdEl) txnIdEl.textContent = `ID Transaksi: #${details.id_transaksi}`;

    // Render purchased products receipt
    if (receiptBox) {
        let receiptHTML = cart.map(item => `
            <div class="receipt-row">
                <span>${item.name} (x${item.qty})</span>
                <span>Rp ${formatRupiah(item.price * item.qty)}</span>
            </div>
        `).join('');

        receiptHTML += `
            <div class="receipt-row total">
                <span>Subtotal</span>
                <span>Rp ${formatRupiah(details.subtotal)}</span>
            </div>
        `;

        if (details.points_redeemed > 0) {
            receiptHTML += `
                <div class="receipt-row" style="color: var(--success-dark); font-weight:600;">
                    <span>Diskon Poin</span>
                    <span>- Rp ${formatRupiah(details.points_redeemed)}</span>
                </div>
            `;
        }

        receiptHTML += `
            <div class="receipt-row total">
                <span>Total Belanja</span>
                <span>Rp ${formatRupiah(details.final_total)}</span>
            </div>
            <div class="receipt-row">
                <span>Metode Pembayaran</span>
                <span>${details.payment_method}</span>
            </div>
        `;

        if (details.score) {
            receiptHTML += `
                <div class="receipt-row">
                    <span>Akurasi Wajah</span>
                    <span>${(details.score * 100).toFixed(1)}%</span>
                </div>
            `;
        }

        receiptBox.innerHTML = receiptHTML;
    }

    // Update points message for members
    if (details.is_member && memberInfoDiv && pointsMsgEl) {
        let msg = `<strong>Nama Member:</strong> ${details.member_name}<br>`;
        if (details.new_saldo !== null) {
            msg += `<strong>Sisa Saldo:</strong> Rp ${formatRupiah(details.new_saldo)}<br>`;
        }
        msg += `<strong>Total Poin:</strong> ${formatRupiah(details.new_points)} Poin`;
        
        pointsMsgEl.innerHTML = msg;
        memberInfoDiv.classList.remove('hidden');
    } else if (memberInfoDiv) {
        memberInfoDiv.classList.add('hidden');
    }

    showModal('modal-success');
}

// Clear cart state and reset interface
function finishTransaction() {
    closeModal('modal-success');
    
    // Clear global cart & states
    cart = [];
    activeMember = null;
    paymentMode = 'regular';
    redeemPointsUsed = 0;

    // Refresh UI
    renderScannedProducts();
    updateCart();

    // Re-sync with database to ensure backend is also clean
    syncCartFromDb();
}
