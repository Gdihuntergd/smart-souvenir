/**
 * Kasir Trinity — Face Verification & Recognition Camera Script (face_camera.js)
 * Manages face detection overlay, camera loops, and triggers face-pay transactions.
 */

// Camera state for verification
let faceStream = null;
let faceDetectTimer = null;
let faceDetectBusy = false;
let faceLastFrame = null;
let faceDetections = [];

// Open Face verification view & start camera
async function startFaceVerifyCamera() {
    const video = document.getElementById('face-verify-camera');
    const statusEl = document.getElementById('face-verify-status');
    const btnText = document.getElementById('face-verify-text');
    const spinner = document.getElementById('face-verify-spinner');
    const btn = document.getElementById('face-verify-btn');
    const resultDiv = document.getElementById('face-verify-result');

    if (!video) return;

    // Reset status & buttons
    if (resultDiv) resultDiv.innerHTML = '';
    if (btnText) btnText.innerHTML = '<i data-lucide="lock" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Verifikasi & Bayar';
    if (spinner) spinner.classList.add('hidden');
    if (btn) btn.disabled = false;
    if (typeof lucide !== 'undefined') lucide.createIcons();

    if (statusEl) {
        statusEl.className = 'camera-status detecting';
        statusEl.innerHTML = `<i data-lucide="scan-search" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Menginisialisasi kamera...`;
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    try {
        faceStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: 640, height: 480 },
            audio: false
        });
        video.srcObject = faceStream;

        if (statusEl) {
            statusEl.innerHTML = `<i data-lucide="scan-search" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Mencari wajah...`;
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }

        // Reset variables
        faceDetections = [];
        faceLastFrame = null;

        // Run fast detection loop for bounding box overlays (feel dynamic & premium)
        faceDetectTimer = setInterval(runFaceDetectionLoop, 300);
    } catch (error) {
        console.error('Gagal mengakses kamera verifikasi:', error);
        if (statusEl) {
            statusEl.className = 'camera-status error';
            statusEl.innerHTML = `<i data-lucide="x-circle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Akses kamera ditolak. Silakan izinkan kamera di browser Anda.`;
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    }
}

// Stop Face verification view & close camera
function stopFaceVerifyCamera() {
    if (faceDetectTimer) {
        clearInterval(faceDetectTimer);
        faceDetectTimer = null;
    }

    if (faceStream) {
        faceStream.getTracks().forEach(track => track.stop());
        faceStream = null;
    }

    const video = document.getElementById('face-verify-camera');
    if (video) video.srcObject = null;

    // Clear canvas
    const canvas = document.getElementById('face-verify-overlay');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    faceDetectBusy = false;
}

// Clean close helper
function closeFaceVerify() {
    stopFaceVerifyCamera();
    closeModal('modal-face-verify');
}

// Extract base64 image frame from video element
function captureFaceFrame(quality = 0.75) {
    const video = document.getElementById('face-verify-camera');
    if (!video || !faceStream) return null;

    const canvas = document.createElement('canvas');
    const maxW = 640;
    const scale = Math.min(1, maxW / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale) || 640;
    canvas.height = Math.round(video.videoHeight * scale) || 480;

    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', quality);
}

// Detection loop to get bounding boxes (without verifying identity)
async function runFaceDetectionLoop() {
    if (faceDetectBusy || !faceStream) return;

    const video = document.getElementById('face-verify-camera');
    if (!video || video.readyState < 2) return;

    faceDetectBusy = true;

    try {
        const image = captureFaceFrame(0.65);
        if (!image) return;

        const response = await fetch('/kasir/api/face/detect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: image })
        });

        const data = await response.json();
        if (!data.ok) return;

        faceLastFrame = data.frame || faceLastFrame;
        faceDetections = data.detections || [];

        // Draw overlays on top of canvas
        drawFaceDetections(faceLastFrame, faceDetections);

        // Update status text
        const statusEl = document.getElementById('face-verify-status');
        if (statusEl) {
            if (faceDetections.length > 0) {
                statusEl.className = 'camera-status success';
                statusEl.innerHTML = `<i data-lucide="user-check" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Wajah Terdeteksi — Tekan tombol Verifikasi di bawah`;
            } else {
                statusEl.className = 'camera-status detecting';
                statusEl.innerHTML = `<i data-lucide="scan-search" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Mencari wajah...`;
            }
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } catch (error) {
        console.error('Error in face detection loop:', error);
    } finally {
        faceDetectBusy = false;
    }
}

// Render bounding boxes on overlay canvas
function drawFaceDetections(frame, detections) {
    const video = document.getElementById('face-verify-camera');
    const canvas = document.getElementById('face-verify-overlay');
    if (!video || !canvas || !frame) return;

    const ctx = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
    
    // Set internal canvas width/height to match high pixel density
    const dpr = window.devicePixelRatio || 1;
    const destW = Math.round(rect.width * dpr);
    const destH = Math.round(rect.height * dpr);
    
    if (canvas.width !== destW || canvas.height !== destH) {
        canvas.width = destW;
        canvas.height = destH;
    }

    const cssW = destW / dpr;
    const cssH = destH / dpr;
    
    const srcW = frame.width || video.videoWidth || 640;
    const srcH = frame.height || video.videoHeight || 480;
    
    const scale = Math.max(cssW / srcW, cssH / srcH);
    const offsetX = (cssW - srcW * scale) / 2;
    const offsetY = (cssH - srcH * scale) / 2;

    ctx.clearRect(0, 0, destW, destH);
    ctx.save();
    ctx.scale(dpr, dpr);
    
    ctx.lineWidth = 3;
    ctx.font = '800 14px Inter, sans-serif';
    ctx.textBaseline = 'top';

    detections.forEach(item => {
        const box = item.box || {};
        const x = (box.x || 0) * scale + offsetX;
        const y = (box.y || 0) * scale + offsetY;
        const w = (box.w || 1) * scale;
        const h = (box.h || 1) * scale;

        const color = 'var(--primary)'; // Sleek indigo border
        const label = 'MEMBER?';

        const labelWidth = Math.min(ctx.measureText(label).width + 16, cssW - 8);
        const labelHeight = 24;
        const labelY = y > 30 ? y - 28 : y + 4;

        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.strokeRect(x, y, w, h);
        
        ctx.fillRect(x, labelY, labelWidth, labelHeight);
        ctx.fillStyle = '#ffffff';
        ctx.fillText(label, x + 8, labelY + 4);
    });

    ctx.restore();
}

// Perform verification and execute payment
async function verifyFaceForPayment() {
    const image = captureFaceFrame(0.85);
    if (!image) {
        alert('Gambar wajah belum siap. Harap tunggu kamera menyala.');
        return;
    }

    const btn = document.getElementById('face-verify-btn');
    const textSpan = document.getElementById('face-verify-text');
    const spinner = document.getElementById('face-verify-spinner');
    const resultDiv = document.getElementById('face-verify-result');

    if (btn) btn.disabled = true;
    if (textSpan) textSpan.textContent = 'Memverifikasi wajah...';
    if (spinner) spinner.classList.remove('hidden');
    if (resultDiv) resultDiv.innerHTML = '';

    // Calculate cart details
    const subtotal = cart.reduce((sum, item) => sum + (item.price * item.qty), 0);
    const redeemPoints = (paymentMode === 'redeem') ? redeemPointsUsed : 0;
    const finalTotal = Math.max(0, subtotal - redeemPoints);
    const earnedPoints = Math.floor(finalTotal / POINTS_PER_RUPIAH);

    const cartPayload = cart.map(item => ({
        product_id: item.product_id,
        quantity: item.qty,
        price: item.price,
        rfid_tag: item.rfid_tag
    }));

    try {
        const response = await fetch('/kasir/api/payment/face-pay', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                image: image,
                cart: cartPayload,
                subtotal: subtotal,
                final_total: finalTotal,
                payment_mode: paymentMode,
                redeem_points: redeemPoints,
                earned_points: earnedPoints
            })
        });

        const data = await response.json();

        if (!data.ok) {
            resultDiv.innerHTML = `
                <div class="alert alert-error">
                    <i data-lucide="x-circle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> ${data.error || 'Pembayaran Face Pay gagal.'}
                </div>
            `;
            if (typeof lucide !== 'undefined') lucide.createIcons();
            return;
        }

        // Successfully paid!
        stopFaceVerifyCamera();
        closeModal('modal-face-verify');
        closeModal('modal-member-dashboard');
        
        // Show success screen (defined in payment.js)
        if (typeof showSuccessScreen === 'function') {
            showSuccessScreen({
                id_transaksi: data.id_transaksi,
                payment_method: 'Face Pay (Saldo)',
                subtotal: subtotal,
                points_redeemed: redeemPoints,
                final_total: finalTotal,
                is_member: true,
                member_name: data.member_name,
                new_saldo: data.new_saldo,
                new_points: data.new_points,
                score: data.score
            });
        }
    } catch (error) {
        console.error('Face Pay transaction error:', error);
        resultDiv.innerHTML = `
            <div class="alert alert-error">
                <i data-lucide="x-circle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Kesalahan jaringan. Pembayaran gagal dilakukan.
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } finally {
        if (btn) btn.disabled = false;
        if (textSpan) textSpan.innerHTML = '<i data-lucide="lock" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Verifikasi & Bayar';
        if (spinner) spinner.classList.add('hidden');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}
