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

export function showLoading(title = 'Processing...', message = 'Please wait while we process your request.') {
    const dialog = loadingDialog();
    if (!dialog) return;
    updateLoadingMessage(title, message);
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
