document.addEventListener('DOMContentLoaded', () => {
    initSearch();
    initBriefing();
    initStatus();
    initLightbox();
});

// Utility: Debounce
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

// OmniSearch
function initSearch() {
    const searchInput = document.getElementById('search-input');
    const resultsContainer = document.getElementById('search-results');

    const performSearch = async (query) => {
        if (!query.trim()) {
            resultsContainer.innerHTML = '';
            return;
        }

        try {
            const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            const data = await response.json();
            renderResults(data.results);
        } catch (error) {
            console.error('Search error:', error);
            resultsContainer.innerHTML = '<p>Error fetching results.</p>';
        }
    };

    const debouncedSearch = debounce((e) => performSearch(e.target.value), 300);
    searchInput.addEventListener('input', debouncedSearch);
}

function renderResults(results) {
    const resultsContainer = document.getElementById('search-results');
    resultsContainer.innerHTML = '';

    if (!results || results.length === 0) {
        resultsContainer.innerHTML = '<p>No results found.</p>';
        return;
    }

    results.forEach(result => {
        const card = document.createElement('div');
        card.className = 'result-card';

        let imageHtml = '';
        if (result.image_url) {
            imageHtml = `<img src="${result.image_url}" class="result-image-preview" alt="Preview" onclick="openLightbox('${result.image_url}')">`;
        }

        card.innerHTML = `
            <div class="result-header">
                <strong>${result.title}</strong>
                <span class="confidence-badge">${(result.confidence * 100).toFixed(0)}% Match</span>
            </div>
            <p>${result.snippet}</p>
            <div>
                ${imageHtml}
            </div>
            <div>
                <span class="timestamp-jumper" onclick="jumpToTimestamp('${result.timestamp}')">Jump to ${result.timestamp}</span>
            </div>
        `;
        resultsContainer.appendChild(card);
    });
}

function jumpToTimestamp(timestamp) {
    alert(`Jump to timestamp: ${timestamp} (Implementation depends on specific media player)`);
}

// Audio Briefing
async function initBriefing() {
    const titleEl = document.getElementById('briefing-title');
    const audioEl = document.getElementById('briefing-audio');

    try {
        const response = await fetch('/api/briefing');
        const data = await response.json();

        titleEl.textContent = data.title || 'Morning Briefing';
        if (data.audio_url) {
            audioEl.src = data.audio_url;
        } else {
             titleEl.textContent = 'Briefing not available';
        }
    } catch (error) {
        console.error('Briefing error:', error);
        titleEl.textContent = 'Error loading briefing';
    }
}

// Status Widget
async function initStatus() {
    const widget = document.getElementById('status-widget');

    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        const isUp = data.status === 'operational' || data.status === 'up';
        const statusClass = isUp ? 'up' : 'down';

        let servicesHtml = '';
        if (data.services) {
            const serviceEntries = Object.entries(data.services).map(([name, status]) => {
                const sClass = (status === 'up' || status === 'operational') ? 'up' : 'down';
                return `<span class="service-status" title="${name}: ${status}"><span class="status-dot ${sClass}"></span> ${name}</span>`;
            }).join(' | ');
            servicesHtml = `<div class="services-details">${serviceEntries}</div>`;
        }

        const statusText = isUp ? 'All Systems Operational' : 'System Issues Detected';

        widget.innerHTML = `
            <div style="display: flex; align-items: center; gap: 10px;">
                <span class="status-dot ${statusClass}"></span> ${statusText}
            </div>
            ${servicesHtml}
        `;
    } catch (error) {
        console.error('Status error:', error);
        widget.innerHTML = `<span class="status-dot down"></span> Status Unavailable`;
    }
}

// Lightbox
function initLightbox() {
    const lightbox = document.getElementById('lightbox');
    const closeBtn = document.querySelector('.close-lightbox');

    closeBtn.onclick = function() {
        lightbox.style.display = "none";
    }

    window.onclick = function(event) {
        if (event.target == lightbox) {
            lightbox.style.display = "none";
        }
    }
}

function openLightbox(src) {
    const lightbox = document.getElementById('lightbox');
    const img = document.getElementById('lightbox-img');
    img.src = src;
    lightbox.style.display = "block";
}
