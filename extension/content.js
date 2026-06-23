let debounceTimer;

function saveState() {
    // Only save state if it's a typical page
    if (!window.location.href.startsWith("http")) return;

    const state = {
        scrollX: window.scrollX,
        scrollY: window.scrollY,
        videoTimes: []
    };

    const videos = document.querySelectorAll('video');
    videos.forEach((vid, index) => {
        // We save the time for any video that has been started
        if (vid.currentTime > 0) {
            state.videoTimes.push({
                index: index,
                time: vid.currentTime
            });
        }
    });

    chrome.runtime.sendMessage({
        action: "saveState",
        url: window.location.href.split('?')[0].split('#')[0], // normalize URL a bit
        state: state
    });
}

// Debounce scrolling and events
window.addEventListener('scroll', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(saveState, 1000);
});

// Periodic save for videos
setInterval(saveState, 3000);

// Restore on load
chrome.runtime.sendMessage({
    action: "getState",
    url: window.location.href.split('?')[0].split('#')[0]
}, (response) => {
    if (response && response.state) {
        const state = response.state;

        // Restore Scroll
        if (state.scrollY || state.scrollX) {
            window.addEventListener('load', () => {
                window.scrollTo({
                    top: state.scrollY || 0,
                    left: state.scrollX || 0,
                    behavior: "smooth"
                });
            });
            // Try immediately in case it's a SPA or already loaded
            setTimeout(() => {
                window.scrollTo({
                    top: state.scrollY || 0,
                    left: state.scrollX || 0,
                    behavior: "smooth"
                });
            }, 1000);
        }

        // Restore Videos
        if (state.videoTimes && state.videoTimes.length > 0) {
            const applyVideoTimes = () => {
                const videos = document.querySelectorAll('video');
                state.videoTimes.forEach(videoState => {
                    const vid = videos[videoState.index];
                    if (vid && !vid.dataset.seeked) {
                        vid.currentTime = videoState.time;
                        vid.dataset.seeked = "true";
                    }
                });
            };

            const observer = new MutationObserver(applyVideoTimes);
            observer.observe(document.body, { childList: true, subtree: true });
            
            setInterval(applyVideoTimes, 1000);
        }
    }
});
