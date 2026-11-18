/**
 * Turning values into text for people.
 */

export function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/** A length of time as on a stopwatch: `0:07`, `12:05`, `1:02:05`. */
export function formatDuration(seconds) {
    const whole = Math.max(0, Math.floor(Number(seconds) || 0));
    const two = (number) => String(number).padStart(2, '0');
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const rest = two(whole % 60);
    return hours > 0 ? `${hours}:${two(minutes)}:${rest}` : `${minutes}:${rest}`;
}

/** `2024-03-04 09:36` in local time, from an ISO date-time ('' when there is none). */
export function formatDateTime(iso) {
    const date = new Date(iso);
    if (!iso || Number.isNaN(date.getTime())) return '';
    const two = (number) => String(number).padStart(2, '0');
    return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())} ${two(date.getHours())}:${two(date.getMinutes())}`;
}
