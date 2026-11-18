/**
 * Weekly calendars, one button per hour: when each resource works, and when
 * new cases can arrive.
 */

import { escapeHtml, on } from '../../core/dom.js';
import { markParametersDirty, state } from '../../core/state.js';
import { revertToOriginalVisualization } from '../petri-net.js';

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

/** The hours of a working day until told otherwise: from 9 to 17. */
export function createDefaultWorkingHours() {
    const hours = {};
    for (let i = 0; i < 24; i++) {
        hours[i.toString()] = (i >= 9 && i < 17);
    }
    return hours;
}

export function renderResourceCalendars(calendars, container) {
    const resourceNames = Object.keys(calendars);

    let html = '<div class="mb-3">';
    html += '<label class="form-label">Select Resource:</label>';
    html += '<select class="form-select form-select-sm mb-2" id="calendarResourceSelect" data-action="show-resource-calendar">';
    html += '<option value="">Choose a resource...</option>';
    resourceNames.forEach(resource => {
        html += `<option value="${escapeHtml(resource)}">${escapeHtml(resource)}</option>`;
    });
    html += '</select>';
    html += '<div id="calendarDisplay" class="border rounded p-2" style="max-height: 300px; overflow-y: auto;">';
    html += resourceNames.length === 0
        ? '<p class="text-muted">No calendar data available</p>'
        : '<p class="text-muted">Select a resource to view calendar</p>';
    html += '</div>';
    html += '</div>';

    container.innerHTML = html;
}

function showResourceCalendar(resourceName) {
    revertToOriginalVisualization();

    const display = document.getElementById('calendarDisplay');
    const calendars = state.parameters.resource_params.calendars;
    if (!resourceName || !calendars || !calendars[resourceName]) {
        display.innerHTML = '<p class="text-muted">No calendar data available</p>';
        return;
    }

    const calendar = calendars[resourceName];
    const name = escapeHtml(resourceName);

    let html = `<h6 class="mb-3">${name} Calendar</h6>`;
    html += '<div class="row">';
    DAYS.forEach(day => {
        if (!calendar[day]) return;
        html += '<div class="col-md-6 mb-3">';
        html += `<h6 class="small">${day}</h6>`;
        html += '<div class="d-flex flex-wrap gap-1">';
        for (let hour = 0; hour < 24; hour++) {
            const isAvailable = calendar[day][hour.toString()] === true;
            html += `
                    <button type="button" class="btn btn-sm calendar-hour-btn ${isAvailable ? 'selected' : ''}"
                            data-action="toggle-resource-hour" data-resource="${name}" data-day="${day}" data-hour="${hour}" data-set="${!isAvailable}">
                        ${hour.toString().padStart(2, '0')}
                    </button>
                `;
        }
        html += '</div></div>';
    });
    html += '</div>';
    display.innerHTML = html;
}

function toggleResourceHour(resourceName, day, hour, isAvailable) {
    markParametersDirty();
    const resourceParams = state.parameters.resource_params;
    if (!resourceParams.calendars) resourceParams.calendars = {};
    if (!resourceParams.calendars[resourceName]) resourceParams.calendars[resourceName] = {};
    if (!resourceParams.calendars[resourceName][day]) resourceParams.calendars[resourceName][day] = {};
    resourceParams.calendars[resourceName][day][hour] = isAvailable;

    showResourceCalendar(resourceName);
}

/** HTML of the calendar of the arrivals. */
export function renderArrivalCalendar(calendar) {
    let html = '<div class="mb-2">';
    html += '<small class="text-muted">Click hours to toggle when new cases can arrive:</small>';
    html += '</div>';

    DAYS.forEach(day => {
        html += '<div class="mb-2">';
        html += `<div class="small fw-bold mb-1">${day.substring(0, 3)}</div>`;
        html += '<div class="d-flex flex-wrap gap-1">';
        // A day the calendar says nothing about is shown with working hours.
        const hours = calendar[day] || createDefaultWorkingHours();
        for (let hour = 0; hour < 24; hour++) {
            const isActive = hours[hour.toString()] === true;
            html += `
                <button type="button" class="btn btn-sm calendar-hour-btn arrival-calendar-hour ${isActive ? 'active' : ''}"
                        data-action="toggle-arrival-hour" data-day="${day}" data-hour="${hour}" data-set="${!isActive}">
                    ${hour.toString().padStart(2, '0')}
                </button>
            `;
        }
        html += '</div></div>';
    });

    return html;
}

function toggleArrivalHour(day, hour, isActive) {
    markParametersDirty();
    if (!state.parameters.inter_arrival_params) state.parameters.inter_arrival_params = {};
    const arrivalParams = state.parameters.inter_arrival_params;
    if (!arrivalParams.inter_arrival_time) arrivalParams.inter_arrival_time = {};
    if (!arrivalParams.inter_arrival_time.calendar) arrivalParams.inter_arrival_time.calendar = {};
    const calendar = arrivalParams.inter_arrival_time.calendar;
    // The days the calendar said nothing about were shown with working
    // hours: write them down, or this click would leave only one hour on.
    for (const name of DAYS) {
        if (!calendar[name]) calendar[name] = createDefaultWorkingHours();
    }
    calendar[day][hour] = isActive;

    const calendarDisplay = document.getElementById('arrivalCalendarDisplay');
    if (calendarDisplay) calendarDisplay.innerHTML = renderArrivalCalendar(calendar);
}

on('change', { 'show-resource-calendar': (element) => showResourceCalendar(element.value) });
on('click', {
    'toggle-resource-hour': (element) => {
        const { resource, day, hour, set } = element.dataset;
        toggleResourceHour(resource, day, hour, set === 'true');
    },
    'toggle-arrival-hour': (element) => {
        const { day, hour, set } = element.dataset;
        toggleArrivalHour(day, hour, set === 'true');
    },
});
