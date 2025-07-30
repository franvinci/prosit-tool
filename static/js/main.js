/**
 * ProSiT - Process Simulation Tool
 * Main JavaScript functionality
 */

// Global variables
let loadingModal;

// Initialize application
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap components
    initializeBootstrap();
    
    // Setup global event handlers
    setupGlobalHandlers();
    
    console.log('ProSiT initialized successfully');
});

function initializeBootstrap() {
    // Initialize loading modal
    const loadingModalElement = document.getElementById('loadingModal');
    if (loadingModalElement) {
        loadingModal = new bootstrap.Modal(loadingModalElement, {
            backdrop: 'static',
            keyboard: false
        });
    }
}

function setupGlobalHandlers() {
    // Handle file input changes
    document.addEventListener('change', function(e) {
        if (e.target.type === 'file') {
            handleFileInputChange(e.target);
        }
    });
    
    // Handle form submissions
    document.addEventListener('submit', function(e) {
        if (e.target.tagName === 'FORM') {
            // Prevent double submissions
            const submitBtn = e.target.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = true;
                setTimeout(() => {
                    submitBtn.disabled = false;
                }, 2000);
            }
        }
    });
}

function handleFileInputChange(input) {
    const file = input.files[0];
    if (!file) return;
    
    // Validate file type
    if (!file.name.toLowerCase().endsWith('.xes')) {
        showAlert('Please select a valid XES file', 'warning');
        input.value = '';
        return;
    }
    
    // Check file size (max 100MB)
    if (file.size > 100 * 1024 * 1024) {
        showAlert('File size too large. Maximum size is 100MB', 'warning');
        input.value = '';
        return;
    }
    
    // Update UI to show selected file
    const fileName = file.name;
    const fileInfo = document.createElement('small');
    fileInfo.className = 'text-muted d-block mt-1';
    fileInfo.textContent = `Selected: ${fileName} (${formatFileSize(file.size)})`;
    
    // Remove existing file info
    const existingInfo = input.parentNode.querySelector('small.text-muted');
    if (existingInfo && existingInfo.textContent.startsWith('Selected:')) {
        existingInfo.remove();
    }
    
    input.parentNode.appendChild(fileInfo);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function showLoading(title = 'Processing...', message = 'Please wait while we process your request.') {
    if (!loadingModal) return;
    
    const titleElement = document.getElementById('loadingMessage');
    const messageElement = document.getElementById('loadingDetail');
    
    if (titleElement) titleElement.textContent = title;
    if (messageElement) messageElement.textContent = message;
    
    loadingModal.show();
}

function hideLoading() {
    if (loadingModal) {
        loadingModal.hide();
    }
}

function updateLoadingMessage(title, message) {
    const titleElement = document.getElementById('loadingMessage');
    const messageElement = document.getElementById('loadingDetail');
    
    if (titleElement) titleElement.textContent = title;
    if (messageElement) messageElement.textContent = message;
}

function showAlert(message, type = 'info', duration = 5000) {
    const alertContainer = document.getElementById('alertContainer');
    if (!alertContainer) return;
    
    // Create alert element
    const alertId = 'alert-' + Date.now();
    const alertHtml = `
        <div id="${alertId}" class="alert alert-${type} alert-dismissible fade show" role="alert">
            <div class="d-flex align-items-center">
                <i data-feather="${getAlertIcon(type)}" class="me-2"></i>
                <div>${message}</div>
                <button type="button" class="btn-close ms-auto" data-bs-dismiss="alert"></button>
            </div>
        </div>
    `;
    
    // Add to container
    alertContainer.insertAdjacentHTML('beforeend', alertHtml);
    
    // Initialize feather icons for the new alert
    const alertElement = document.getElementById(alertId);
    feather.replace({ 'data-feather': getAlertIcon(type) });
    
    // Auto-dismiss after duration
    if (duration > 0) {
        setTimeout(() => {
            const alert = document.getElementById(alertId);
            if (alert) {
                const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
                bsAlert.close();
            }
        }, duration);
    }
}

function getAlertIcon(type) {
    const icons = {
        'success': 'check-circle',
        'danger': 'alert-circle',
        'warning': 'alert-triangle',
        'info': 'info'
    };
    return icons[type] || 'info';
}

function validateParameters(parameters) {
    const errors = [];
    
    // Validate structure
    const requiredSections = [
        'transition_params',
        'resource_params', 
        'execution_time_params',
        'waiting_time_params'
    ];
    
    for (const section of requiredSections) {
        if (!parameters[section]) {
            errors.push(`Missing required section: ${section}`);
        }
    }
    
    // Validate transition parameters
    if (parameters.transition_params) {
        const weights = parameters.transition_params.transition_weights || {};
        for (const [transition, weight] of Object.entries(weights)) {
            if (typeof weight !== 'number' || weight < 0 || weight > 1) {
                errors.push(`Invalid transition weight for ${transition}: ${weight}`);
            }
        }
    }
    
    // Validate resource parameters
    if (parameters.resource_params) {
        const resourceWeights = parameters.resource_params.resource_weights || {};
        for (const [resource, weight] of Object.entries(resourceWeights)) {
            if (typeof weight !== 'number' || weight < 0 || weight > 1) {
                errors.push(`Invalid resource weight for ${resource}: ${weight}`);
            }
        }
    }
    
    // Validate execution time parameters
    if (parameters.execution_time_params) {
        const durations = parameters.execution_time_params.activity_durations || {};
        for (const [activity, params] of Object.entries(durations)) {
            if (!params.distribution || !params.mean) {
                errors.push(`Invalid duration parameters for ${activity}`);
            }
            if (params.mean <= 0) {
                errors.push(`Mean duration must be positive for ${activity}`);
            }
            if (params.min && params.max && params.min >= params.max) {
                errors.push(`Minimum duration must be less than maximum for ${activity}`);
            }
        }
    }
    
    return errors;
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function throttle(func, limit) {
    let inThrottle;
    return function() {
        const args = arguments;
        const context = this;
        if (!inThrottle) {
            func.apply(context, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Utility functions for parameter manipulation
function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}

function downloadJSON(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { 
        type: 'application/json' 
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(url);
    document.body.removeChild(a);
}

function formatDateTime(date) {
    return new Intl.DateTimeFormat('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    }).format(new Date(date));
}

function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
}

// Export functions for global use
window.ProSiT = {
    showLoading,
    hideLoading,
    updateLoadingMessage,
    showAlert,
    validateParameters,
    debounce,
    throttle,
    deepClone,
    downloadJSON,
    formatDateTime,
    formatFileSize,
    generateId
};
