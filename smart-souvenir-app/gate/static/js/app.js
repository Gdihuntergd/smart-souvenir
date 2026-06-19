/**
 * Smart Souvenir - Gate Component
 * Main JavaScript Application
 */

// ============================================================
// Utility Functions
// ============================================================

/**
 * Show a toast notification
 * @param {string} message - The message to show
 * @param {string} type - 'success', 'error', 'warning', 'info'
 * @param {number} duration - Duration in ms (default 3000)
 */
function showToast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    const icons = {
        success: 'fas fa-check-circle',
        error: 'fas fa-times-circle',
        warning: 'fas fa-exclamation-triangle',
        info: 'fas fa-info-circle'
    };
    
    toast.innerHTML = `
        <i class="${icons[type] || icons.info}"></i>
        <span>${message}</span>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

/**
 * Format a date/time string
 * @param {string} isoString - ISO date string
 * @returns {string} Formatted date
 */
function formatDateTime(isoString) {
    if (!isoString) return '-';
    const date = new Date(isoString);
    return date.toLocaleString('id-ID', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
}

/**
 * Make an API call
 * @param {string} url - API endpoint
 * @param {object} options - Fetch options
 * @returns {Promise<any>} Response data
 */
async function apiCall(url, options = {}) {
    try {
        const res = await fetch(url, {
            headers: { 'Content-Type': 'application/json' },
            ...options
        });
        
        if (!res.ok) {
            const error = await res.json().catch(() => ({ error: 'Request failed' }));
            throw new Error(error.error || `HTTP ${res.status}`);
        }
        
        return await res.json();
    } catch (err) {
        console.error(`API Error (${url}):`, err);
        throw err;
    }
}

// ============================================================
// Sidebar Toggle
// ============================================================

function toggleSidebar() {
    const sidebar = document.querySelector('.sidebar');
    sidebar.classList.toggle('open');
}

// Close sidebar on outside click (mobile)
document.addEventListener('click', (e) => {
    const sidebar = document.querySelector('.sidebar');
    const menuToggle = document.querySelector('.menu-toggle');
    
    if (sidebar && sidebar.classList.contains('open')) {
        if (!sidebar.contains(e.target) && !menuToggle?.contains(e.target)) {
            sidebar.classList.remove('open');
        }
    }
});

// ============================================================
// DateTime Update
// ============================================================

function updateDateTime() {
    const el = document.getElementById('datetime');
    if (el) {
        const now = new Date();
        el.textContent = now.toLocaleString('id-ID', {
            weekday: 'short',
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    }
}

// Update every second
setInterval(updateDateTime, 1000);
updateDateTime();

// ============================================================
// Gate Status Polling
// ============================================================

let lastGateStatus = null;

async function pollGateStatus() {
    try {
        const data = await apiCall('/gate/api/gate/status');
        
        // Update gate badge if changed
        if (lastGateStatus !== data.status) {
            lastGateStatus = data.status;
            
            const badge = document.getElementById('gateBadge');
            if (badge) {
                badge.className = `badge badge-${data.status === 'open' ? 'success' : 'danger'}`;
                badge.innerHTML = `<i class="fas fa-door-${data.status === 'open' ? 'open' : 'closed'}"></i> ${data.status.toUpperCase()}`;
            }
        }
        
        // Update camera badge — check both server state and browser webcam flag
        const camBadge = document.getElementById('cameraBadge');
        if (camBadge) {
            const isBrowserCam = (typeof window.browserCamActive !== 'undefined') && window.browserCamActive;
            const camActive = data.camera_active || isBrowserCam;
            camBadge.className = `badge badge-${camActive ? 'success' : 'secondary'}`;
            camBadge.innerHTML = `<i class="fas fa-video"></i> ${camActive ? 'Kamera Aktif' : 'Kamera Off'}`;
        }
    } catch (err) {
        // Silent fail for polling
    }
}

// Poll every 5 seconds
setInterval(pollGateStatus, 5000);

// ============================================================
// Keyboard Shortcuts
// ============================================================

document.addEventListener('keydown', (e) => {
    // Ctrl/Cmd + K = Quick search
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.getElementById('searchInput');
        if (searchInput) searchInput.focus();
    }
    
    // Escape = Close modals
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal.active').forEach(modal => {
            modal.classList.remove('active');
        });
    }
});

// ============================================================
// Initialization
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('%c Smart Souvenir - Gate Component ', 
        'background: linear-gradient(135deg, #667eea, #764ba2); color: white; font-size: 14px; padding: 8px 16px; border-radius: 4px;');
    console.log('Web application initialized successfully');
});
