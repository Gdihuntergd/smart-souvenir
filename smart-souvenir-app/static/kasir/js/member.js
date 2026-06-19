/**
 * Kasir Trinity — Member Management Script (member.js)
 * Handles login lookup, registration (with optional face enrollment), and balance top-ups.
 */

// Global state for active member
let activeMember = null;

// Camera state for registration enrollment
let regStream = null;
let regFaceCaptured = null; // Stores base64 data-url

// Update Dashboard UI with active member's statistics
function updateDashboardUI() {
    if (!activeMember) return;
    
    const nameEl = document.getElementById('dash-member-name');
    const pointsEl = document.getElementById('dash-member-points');
    const saldoEl = document.getElementById('dash-member-saldo');

    if (nameEl) nameEl.textContent = activeMember.name;
    if (pointsEl) pointsEl.textContent = formatRupiah(activeMember.points);
    if (saldoEl) saldoEl.textContent = `Rp ${formatRupiah(activeMember.saldo)}`;

    // Update point calculation and payment modes in payment.js if loaded
    if (typeof updatePaymentOptions === 'function') {
        updatePaymentOptions();
    }
}

// Camera state for login
let loginStream = null;
let loginDetectTimer = null;
let loginDetectBusy = false;
let loginLastFrame = null;
let loginDetections = [];

// Trigger login modal & start camera
function startMemberLoginFlow() {
    showModal('modal-member-login');
    startMemberLoginCamera();
}

// Close Member Login view
function closeMemberLogin() {
    stopMemberLoginCamera();
    closeModal('modal-member-login');
}

// Start Member Login camera stream
async function startMemberLoginCamera() {
    const video = document.getElementById('member-login-camera');
    const statusEl = document.getElementById('member-login-status');
    const btnText = document.getElementById('member-login-text');
    const spinner = document.getElementById('member-login-spinner');
    const btn = document.getElementById('member-login-btn');
    const resultDiv = document.getElementById('member-login-result');

    if (!video) return;

    if (resultDiv) resultDiv.innerHTML = '';
    if (btnText) btnText.innerHTML = '<i data-lucide="lock" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Verifikasi & Masuk';
    if (spinner) spinner.classList.add('hidden');
    if (btn) btn.disabled = false;

    if (statusEl) {
        statusEl.className = 'camera-status detecting';
        statusEl.innerHTML = `<i data-lucide="scan-search" style="width:16px;height:16px;display:inline;"></i> Menginisialisasi kamera...`;
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();

    try {
        loginStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: 640, height: 480 },
            audio: false
        });
        video.srcObject = loginStream;

        if (statusEl) {
            statusEl.innerHTML = `<i data-lucide="scan-search" style="width:16px;height:16px;display:inline;"></i> Mencari wajah...`;
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }

        loginDetections = [];
        loginLastFrame = null;
        loginDetectTimer = setInterval(runLoginFaceDetectionLoop, 300);
    } catch (error) {
        console.error('Gagal mengakses kamera login:', error);
        if (statusEl) {
            statusEl.className = 'camera-status error';
            statusEl.innerHTML = `<i data-lucide="x-circle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Akses kamera ditolak. Silakan izinkan kamera di browser Anda.`;
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    }
}

// Stop Member Login camera stream
function stopMemberLoginCamera() {
    if (loginDetectTimer) {
        clearInterval(loginDetectTimer);
        loginDetectTimer = null;
    }
    if (loginStream) {
        loginStream.getTracks().forEach(track => track.stop());
        loginStream = null;
    }
    const video = document.getElementById('member-login-camera');
    if (video) video.srcObject = null;

    const canvas = document.getElementById('member-login-overlay');
    if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    loginDetectBusy = false;
}

// Capture frame for login processing
function captureLoginFaceFrame(quality = 0.75) {
    const video = document.getElementById('member-login-camera');
    if (!video || !loginStream) return null;

    const canvas = document.createElement('canvas');
    const maxW = 640;
    const scale = Math.min(1, maxW / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale) || 640;
    canvas.height = Math.round(video.videoHeight * scale) || 480;

    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', quality);
}

// Fast face detection loop for overlay feedback during login
async function runLoginFaceDetectionLoop() {
    if (loginDetectBusy || !loginStream) return;

    const video = document.getElementById('member-login-camera');
    if (!video || video.readyState < 2) return;

    loginDetectBusy = true;

    try {
        const image = captureLoginFaceFrame(0.65);
        if (!image) return;

        const response = await fetch('/kasir/api/face/detect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: image })
        });

        const data = await response.json();
        if (!data.ok) return;

        loginLastFrame = data.frame || loginLastFrame;
        loginDetections = data.detections || [];

        drawLoginFaceDetections(loginLastFrame, loginDetections);

        const statusEl = document.getElementById('member-login-status');
        if (statusEl) {
            if (loginDetections.length > 0) {
                statusEl.className = 'camera-status success';
                statusEl.innerHTML = `<i data-lucide="user-check" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Wajah Terdeteksi — Tekan tombol Verifikasi di bawah`;
            } else {
                statusEl.className = 'camera-status detecting';
                statusEl.innerHTML = `<i data-lucide="scan-search" style="width:16px;height:16px;display:inline;"></i> Mencari wajah...`;
            }
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } catch (error) {
        console.error('Error in login face detection loop:', error);
    } finally {
        loginDetectBusy = false;
    }
}

// Draw bounding box feedback for login view
function drawLoginFaceDetections(frame, detections) {
    const video = document.getElementById('member-login-camera');
    const canvas = document.getElementById('member-login-overlay');
    if (!video || !canvas || !frame) return;

    const ctx = canvas.getContext('2d');
    const rect = canvas.getBoundingClientRect();
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

        const color = 'var(--primary)';
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

// Perform verification and execute member login
async function verifyFaceForLogin() {
    const image = captureLoginFaceFrame(0.85);
    if (!image) {
        alert('Kamera login belum siap. Harap tunggu.');
        return;
    }

    const btn = document.getElementById('member-login-btn');
    const textSpan = document.getElementById('member-login-text');
    const spinner = document.getElementById('member-login-spinner');
    const resultDiv = document.getElementById('member-login-result');

    if (btn) btn.disabled = true;
    if (textSpan) textSpan.textContent = 'Memverifikasi wajah...';
    if (spinner) spinner.classList.remove('hidden');
    if (resultDiv) resultDiv.innerHTML = '';

    try {
        const response = await fetch('/kasir/api/face/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: image })
        });

        const data = await response.json();

        if (!data.ok) {
            resultDiv.innerHTML = `
                <div class="alert alert-error">
                    <i data-lucide="x-circle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> ${data.error || 'Login verifikasi wajah gagal.'}
                </div>
            `;
            return;
        }

        if (data.status === 'NOT_RECOGNIZED' || !data.member) {
            resultDiv.innerHTML = `
                <div class="alert alert-warning flex flex-col gap-2">
                    <span><i data-lucide="alert-triangle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Wajah tidak terdaftar sebagai member.</span>
                    <button class="btn btn-sm btn-ghost mt-1 w-full" type="button" onclick="openRegisterModalFromLogin()">
                        <i data-lucide="user-plus" style="width:14px;height:14px;display:inline;vertical-align:middle;"></i> Daftar Member Baru
                    </button>
                </div>
            `;
            return;
        }

        // Recognized successfully!
        activeMember = data.member;
        if (activeMember) {
            activeMember.has_face = true;
        }
        updateDashboardUI();

        stopMemberLoginCamera();
        closeModal('modal-member-login');
        showModal('modal-member-dashboard');
    } catch (error) {
        console.error('Member login verification error:', error);
        resultDiv.innerHTML = `
            <div class="alert alert-error">
                <i data-lucide="x-circle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Kesalahan jaringan. Login gagal dilakukan.
            </div>
        `;
    } finally {
        if (btn) btn.disabled = false;
        if (textSpan) textSpan.innerHTML = '<i data-lucide="lock" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Verifikasi & Masuk';
        if (spinner) spinner.classList.add('hidden');
    }
}

// Transition: login face unrecognized -> register modal
function openRegisterModalFromLogin() {
    closeMemberLogin();
    showModal('modal-register');
}

// Open Register Modal (Clean state)
function openRegisterModal() {
    closeModal('modal-nonmember');
    showModal('modal-register');
    
    // Reset inputs & preview
    const form = document.getElementById('register-form');
    if (form) form.reset();
    
    const preview = document.getElementById('reg-face-preview');
    if (preview) preview.classList.add('hidden');
    
    regFaceCaptured = null;
    stopRegisterCamera();
}

// Toggle Enrollment Camera for registration
async function toggleRegisterCamera() {
    const container = document.getElementById('register-camera-container');
    const video = document.getElementById('register-camera');
    const toggleBtn = document.getElementById('reg-camera-toggle');
    const captureBtn = document.getElementById('reg-capture-btn');
    const preview = document.getElementById('reg-face-preview');

    if (!container || !video || !toggleBtn || !captureBtn) return;

    if (regStream) {
        stopRegisterCamera();
    } else {
        try {
            regStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'user', width: 640, height: 480 },
                audio: false
            });
            video.srcObject = regStream;
            container.classList.remove('hidden');
            if (preview) preview.classList.add('hidden');
            regFaceCaptured = null;
            toggleBtn.innerHTML = '<i data-lucide="camera-off" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Tutup Kamera';
            toggleBtn.className = 'btn btn-danger btn-block';
            captureBtn.classList.remove('hidden');
            if (typeof lucide !== 'undefined') lucide.createIcons();
        } catch (error) {
            console.error('Kamera enrollment tidak aktif:', error);
            alert('Tidak dapat mengakses kamera. Silakan periksa izin kamera Anda.');
        }
    }
}

// Stop Enrollment Camera stream
function stopRegisterCamera() {
    const container = document.getElementById('register-camera-container');
    const video = document.getElementById('register-camera');
    const toggleBtn = document.getElementById('reg-camera-toggle');
    const captureBtn = document.getElementById('reg-capture-btn');

    if (regStream) {
        regStream.getTracks().forEach(track => track.stop());
        regStream = null;
    }

    if (video) video.srcObject = null;
    if (container) container.classList.add('hidden');
    
    if (toggleBtn) {
        toggleBtn.innerHTML = '<i data-lucide="camera" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Buka Kamera';
        toggleBtn.className = 'btn btn-ghost btn-block';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
    if (captureBtn) captureBtn.classList.add('hidden');
}

// Capture current frame from registration video stream
function captureRegisterFace() {
    const video = document.getElementById('register-camera');
    const preview = document.getElementById('reg-face-preview');
    const previewImg = document.getElementById('reg-face-img');

    if (!video || !regStream || !preview || !previewImg) return;

    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Compress as JPEG
    regFaceCaptured = canvas.toDataURL('image/jpeg', 0.82);
    previewImg.src = regFaceCaptured;

    preview.classList.remove('hidden');
    stopRegisterCamera();
}

// Handle Register Form Submission (includes member insertion and face enrollment)
async function handleRegister(event) {
    event.preventDefault();

    const name = document.getElementById('reg-name').value.trim();
    const nik = document.getElementById('reg-nik').value.trim();
    const phone = document.getElementById('reg-phone').value.trim();
    const address = document.getElementById('reg-address').value.trim();

    const submitBtn = document.querySelector('#register-form button[type="submit"]');
    const textSpan = document.getElementById('reg-submit-text');
    const spinner = document.getElementById('reg-submit-spinner');
    const resultDiv = document.getElementById('register-result');

    if (!name || !nik || !phone) return;

    // Show loading spinner
    if (submitBtn) submitBtn.disabled = true;
    if (textSpan) textSpan.classList.add('hidden');
    if (spinner) spinner.classList.remove('hidden');
    if (resultDiv) resultDiv.innerHTML = '';

    try {
        // Step 1: Register member metadata
        const response = await fetch('/kasir/api/member/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                nik: nik,
                phone: phone,
                address: address
            })
        });

        const data = await response.json();

        if (!data.ok) {
            resultDiv.innerHTML = `
                <div class="alert alert-error">
                    <i data-lucide="x-circle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> ${data.error || 'Pendaftaran member gagal'}
                </div>
            `;
            if (typeof lucide !== 'undefined') lucide.createIcons();
            return;
        }

        let faceMessage = '';

        // Step 2: If face captured, enroll it
        if (regFaceCaptured) {
            try {
                const faceResponse = await fetch('/kasir/api/member/enroll-face', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        nik: data.nik,
                        image: regFaceCaptured
                    })
                });
                const faceData = await faceResponse.json();
                if (!faceData.ok) {
                    faceMessage = `<br><i data-lucide="alert-triangle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Wajah gagal didaftarkan: ${faceData.error}`;
                } else {
                    faceMessage = '<br><i data-lucide="check-circle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Wajah berhasil didaftarkan!';
                }
            } catch (err) {
                faceMessage = '<br><i data-lucide="alert-triangle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Gagal mengirim data wajah (kesalahan jaringan)';
                console.error(err);
            }
        }

        // Successfully registered
        activeMember = {
            nik: data.nik,
            name: name,
            phone: phone,
            points: data.welcome_points || 100,
            saldo: 0,
            has_face: regFaceCaptured && faceMessage.includes('berhasil')
        };

        // UI success feedback
        resultDiv.innerHTML = `
            <div class="alert alert-success">
                <i data-lucide="party-popper" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Member baru berhasil didaftarkan!${faceMessage}
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();

        // Wait a brief moment to show success message, then transition to dashboard
        setTimeout(() => {
            closeModal('modal-register');
            updateDashboardUI();
            showModal('modal-member-dashboard');
            resultDiv.innerHTML = '';
        }, 1800);

    } catch (error) {
        console.error('Registration error:', error);
        resultDiv.innerHTML = `
            <div class="alert alert-error">
                <i data-lucide="x-circle" style="width:16px;height:16px;display:inline;vertical-align:middle;"></i> Terjadi kesalahan pendaftaran. Silakan coba lagi.
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } finally {
        if (submitBtn) submitBtn.disabled = false;
        if (textSpan) textSpan.classList.remove('hidden');
        if (spinner) spinner.classList.add('hidden');
    }
}

// ------------------------------------
// Dashboard & Top Up UI Functions
// ------------------------------------

let topupSelectedAmount = 0;

function showTopup() {
    const dashboardPayOptions = document.getElementById('member-pay-options');
    const topupSection = document.getElementById('topup-section');
    
    if (dashboardPayOptions) dashboardPayOptions.classList.add('hidden');
    if (topupSection) topupSection.classList.remove('hidden');

    // Default select Rp 50.000
    selectTopup(50000);
}

function hideTopup() {
    const dashboardPayOptions = document.getElementById('member-pay-options');
    const topupSection = document.getElementById('topup-section');
    
    if (dashboardPayOptions) dashboardPayOptions.classList.remove('hidden');
    if (topupSection) topupSection.classList.add('hidden');
}

function selectTopup(amount) {
    topupSelectedAmount = amount;
    
    // Handle selected state on chips
    const chips = document.querySelectorAll('.topup-chip');
    chips.forEach(chip => {
        chip.classList.remove('selected');
        
        // Chip text mapping
        const chipText = chip.textContent.replace(/[^0-9]/g, '');
        if (amount === 0 && chip.textContent.toLowerCase().includes('custom')) {
            chip.classList.add('selected');
        } else if (Number(chipText) === amount && amount > 0) {
            chip.classList.add('selected');
        }
    });

    // Handle custom input display
    const customGroup = document.getElementById('topup-custom-group');
    const customInput = document.getElementById('topup-custom-amount');
    
    if (amount === 0) {
        if (customGroup) customGroup.classList.remove('hidden');
        if (customInput) {
            customInput.value = '';
            customInput.focus();
        }
    } else {
        if (customGroup) customGroup.classList.add('hidden');
    }
}

// Process Balance Top Up
async function processTopup() {
    if (!activeMember) return;

    let finalAmount = topupSelectedAmount;

    // Handle custom amount
    if (topupSelectedAmount === 0) {
        const customInput = document.getElementById('topup-custom-amount');
        if (!customInput) return;

        finalAmount = Number(customInput.value);
        if (isNaN(finalAmount) || finalAmount <= 0) {
            alert('Masukkan jumlah top-up yang valid!');
            return;
        }
    }

    try {
        const response = await fetch('/kasir/api/member/topup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                nik: activeMember.nik,
                amount: finalAmount
            })
        });

        const data = await response.json();

        if (!data.ok) {
            alert(data.error || 'Gagal memproses top-up');
            return;
        }

        // Update active member saldo
        activeMember.saldo = data.new_saldo;
        updateDashboardUI();
        alert(`Berhasil mengisi saldo sebesar Rp ${formatRupiah(finalAmount)}!`);
        hideTopup();
    } catch (error) {
        console.error('Topup balance error:', error);
        alert('Kesalahan jaringan. Top-up gagal dilakukan.');
    }
}
