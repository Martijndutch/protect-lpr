document.addEventListener('DOMContentLoaded', () => {
    const streamsTable = document.querySelector('#streams-table tbody');
    const platesList = document.querySelector('#plates-list');
    const addStreamBtn = document.querySelector('#add-stream-btn');
    const addPlateBtn = document.querySelector('#add-plate-btn');
    const newPlateInput = document.querySelector('#new-plate');
    const saveBtn = document.querySelector('#save-btn');
    const statusMessage = document.querySelector('#status-message');
    const streamModal = document.querySelector('#stream-modal');
    const streamForm = document.querySelector('#stream-form');
    const cancelStreamBtn = document.querySelector('#cancel-stream-btn');

    let config = { rtsp_streams: {}, ignored_plates: [] };

    // Fetch initial config
    fetchConfig();

    function fetchConfig() {
        fetch('/api/config')
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    config = data.config;
                    renderStreams();
                    renderPlates();
                } else {
                    showStatus('Failed to load configuration: ' + data.error);
                }
            })
            .catch(error => showStatus('Error: ' + error.message));
    }

    function renderStreams() {
        streamsTable.innerHTML = '';
        for (const deviceId in config.rtsp_streams) {
            config.rtsp_streams[deviceId].forEach((stream, index) => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="border p-2">${deviceId}</td>
                    <td class="border p-2">${stream.name}</td>
                    <td class="border p-2">${stream.url}</td>
                    <td class="border p-2">${stream.initial_delay_ms}</td>
                    <td class="border p-2">${stream.num_images}</td>
                    <td class="border p-2">${stream.interval_ms}</td>
                    <td class="border p-2">${stream.video_duration_s}</td>
                    <td class="border p-2">
                        <button class="edit-btn bg-yellow-500 text-white px-2 py-1 mr-2" data-device-id="${deviceId}" data-index="${index}">Edit</button>
                        <button class="delete-btn bg-red-500 text-white px-2 py-1" data-device-id="${deviceId}" data-index="${index}">Delete</button>
                    </td>
                `;
                streamsTable.appendChild(row);
            });
        }

        // Attach event listeners for edit and delete buttons
        document.querySelectorAll('.edit-btn').forEach(btn => {
            btn.addEventListener('click', () => editStream(btn.dataset.deviceId, btn.dataset.index));
        });
        document.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', () => deleteStream(btn.dataset.deviceId, btn.dataset.index));
        });
    }

    function renderPlates() {
        platesList.innerHTML = '';
        config.ignored_plates.forEach((plate, index) => {
            const li = document.createElement('li');
            li.className = 'flex justify-between items-center border-b py-2';
            li.innerHTML = `
                <span>${plate}</span>
                <button class="delete-plate-btn bg-red-500 text-white px-2 py-1" data-index="${index}">Remove</button>
            `;
            platesList.appendChild(li);
        });

        // Attach event listeners for delete plate buttons
        document.querySelectorAll('.delete-plate-btn').forEach(btn => {
            btn.addEventListener('click', () => deletePlate(btn.dataset.index));
        });
    }

    function showStatus(message, isError = true) {
        statusMessage.textContent = message;
        statusMessage.classList.remove('hidden');
        statusMessage.classList.toggle('text-red-500', isError);
        statusMessage.classList.toggle('text-green-500', !isError);
        setTimeout(() => statusMessage.classList.add('hidden'), 5000);
    }

    function editStream(deviceId, index) {
        const stream = config.rtsp_streams[deviceId][index];
        document.querySelector('#device-id').value = deviceId;
        document.querySelector('#edit-device-id').value = deviceId;
        document.querySelector('#edit-stream-index').value = index;
        document.querySelector('#name').value = stream.name;
        document.querySelector('#url').value = stream.url;
        document.querySelector('#initial_delay_ms').value = stream.initial_delay_ms;
        document.querySelector('#num_images').value = stream.num_images;
        document.querySelector('#interval_ms').value = stream.interval_ms;
        document.querySelector('#video_duration_s').value = stream.video_duration_s;
        streamModal.classList.remove('hidden');
    }

    function deleteStream(deviceId, index) {
        if (confirm(`Delete stream ${config.rtsp_streams[deviceId][index].name} for device ${deviceId}?`)) {
            config.rtsp_streams[deviceId].splice(index, 1);
            if (config.rtsp_streams[deviceId].length === 0) {
                delete config.rtsp_streams[deviceId];
            }
            renderStreams();
        }
    }

    function deletePlate(index) {
        if (confirm(`Remove plate ${config.ignored_plates[index]}?`)) {
            config.ignored_plates.splice(index, 1);
            renderPlates();
        }
    }

    addStreamBtn.addEventListener('click', () => {
        streamForm.reset();
        document.querySelector('#edit-device-id').value = '';
        document.querySelector('#edit-stream-index').value = '';
        streamModal.classList.remove('hidden');
    });

    addPlateBtn.addEventListener('click', () => {
        const plate = newPlateInput.value.trim();
        if (plate && !config.ignored_plates.includes(plate)) {
            config.ignored_plates.push(plate);
            renderPlates();
            newPlateInput.value = '';
        } else if (!plate) {
            showStatus('Please enter a license plate');
        } else {
            showStatus('Plate already exists');
        }
    });

    streamForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const deviceId = document.querySelector('#device-id').value.trim();
        const editDeviceId = document.querySelector('#edit-device-id').value;
        const editIndex = document.querySelector('#edit-stream-index').value;
        const stream = {
            name: document.querySelector('#name').value.trim(),
            url: document.querySelector('#url').value.trim(),
            initial_delay_ms: parseInt(document.querySelector('#initial_delay_ms').value),
            num_images: parseInt(document.querySelector('#num_images').value),
            interval_ms: parseInt(document.querySelector('#interval_ms').value),
            video_duration_s: parseInt(document.querySelector('#video_duration_s').value)
        };

        if (!config.rtsp_streams[deviceId]) {
            config.rtsp_streams[deviceId] = [];
        }

        if (editDeviceId && editIndex !== '') {
            if (editDeviceId !== deviceId) {
                config.rtsp_streams[editDeviceId].splice(editIndex, 1);
                if (config.rtsp_streams[editDeviceId].length === 0) {
                    delete config.rtsp_streams[editDeviceId];
                }
                config.rtsp_streams[deviceId].push(stream);
            } else {
                config.rtsp_streams[deviceId][editIndex] = stream;
            }
        } else {
            config.rtsp_streams[deviceId].push(stream);
        }

        renderStreams();
        streamModal.classList.add('hidden');
    });

    cancelStreamBtn.addEventListener('click', () => {
        streamModal.classList.add('hidden');
    });

    saveBtn.addEventListener('click', () => {
        fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    showStatus('Configuration saved successfully', false);
                } else {
                    showStatus('Failed to save configuration: ' + data.error);
                }
            })
            .catch(error => showStatus('Error: ' + error.message));
    });
});
