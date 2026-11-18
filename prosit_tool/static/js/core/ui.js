/**
 * Feedback shared by every screen: the loading dialog and the alerts.
 */

let loadingModal = null;
// Whether the dialog should be on screen now. Bootstrap ignores a request to
// hide a dialog that is still fading in (and one to show it while it fades
// out), so the request is repeated when the animation ends.
let loadingWanted = false;

function loadingDialog() {
    if (!loadingModal) {
        const element = document.getElementById('loadingModal');
        if (element && window.bootstrap) {
            loadingModal = new bootstrap.Modal(element, { backdrop: 'static', keyboard: false });
            element.addEventListener('shown.bs.modal', () => { if (!loadingWanted) loadingModal.hide(); });
            element.addEventListener('hidden.bs.modal', () => { if (loadingWanted) loadingModal.show(); });
        }
    }
    return loadingModal;
}

export function updateLoadingMessage(title, message) {
    const titleElement = document.getElementById('loadingMessage');
    const messageElement = document.getElementById('loadingDetail');
    if (titleElement) titleElement.textContent = title;
    if (messageElement) messageElement.textContent = message;
}

/**
 * Show in the loading dialog how far the operation has got: `percent` (0 to
 * 100) fills the bar, the texts go under it (`step` and `count` on the left,
 * `percentText` and `elapsed` on the right). `null` takes the bar away.
 */
export function setLoadingProgress(progress) {
    const area = document.getElementById('loadingProgress');
    if (!area) return;
    area.classList.toggle('d-none', !progress);

    const percent = progress ? Math.min(100, Math.max(0, Number(progress.percent) || 0)) : 0;
    // Emptied while it is out of sight, so that the next one starts from zero.
    document.getElementById('loadingProgressBar').style.width = `${percent}%`;
    document.getElementById('loadingProgressTrack').setAttribute('aria-valuenow', String(Math.floor(percent)));
    const texts = {
        loadingProgressStep: progress && progress.step,
        loadingProgressPercent: progress && progress.percentText,
        loadingProgressCount: progress && progress.count,
        loadingProgressElapsed: progress && progress.elapsed,
    };
    for (const [id, text] of Object.entries(texts)) {
        document.getElementById(id).textContent = text || '';
    }
}

export function showLoading(title = 'Processing...', message = 'Please wait while we process your request.') {
    const dialog = loadingDialog();
    if (!dialog) return;
    updateLoadingMessage(title, message);
    // The bar belongs to the operation that asks for it, not to the one before.
    setLoadingProgress(null);
    loadingWanted = true;
    dialog.show();
}

export function hideLoading() {
    loadingWanted = false;
    if (loadingModal) loadingModal.hide();
}

const ALERT_ICONS = {
    success: 'check-circle',
    danger: 'alert-circle',
    warning: 'alert-triangle',
    info: 'info',
};

/**
 * Show a dismissible message in the corner of the page.
 *
 * `message` is plain text: whatever it contains (a name from an event log, an
 * error from the server) is shown as written, never interpreted as HTML.
 * A `duration` of 0 keeps the alert until the user closes it.
 */
export function showAlert(message, type = 'info', duration = 5000) {
    const container = document.getElementById('alertContainer');
    if (!container) return;
    if (!ALERT_ICONS[type]) type = 'info';

    const alert = document.createElement('div');
    alert.className = `alert alert-${type} alert-dismissible fade show`;
    alert.setAttribute('role', 'alert');
    alert.innerHTML = `
        <div class="d-flex align-items-center">
            <i data-feather="${ALERT_ICONS[type]}" class="me-2"></i>
            <div class="alert-message"></div>
            <button type="button" class="btn-close ms-auto" data-bs-dismiss="alert"></button>
        </div>`;
    alert.querySelector('.alert-message').textContent = message;
    container.appendChild(alert);
    feather.replace();

    if (duration > 0) {
        setTimeout(() => {
            if (alert.isConnected) bootstrap.Alert.getOrCreateInstance(alert).close();
        }, duration);
    }
}
