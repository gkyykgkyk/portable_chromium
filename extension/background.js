chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "saveState") {
        let urlKey = "state_" + request.url;
        let data = {};
        data[urlKey] = request.state;
        chrome.storage.local.set(data);
    }
    else if (request.action === "getState") {
        let urlKey = "state_" + request.url;
        chrome.storage.local.get([urlKey], (result) => {
            sendResponse({ state: result[urlKey] });
        });
        return true; 
    }
});
