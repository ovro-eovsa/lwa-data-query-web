// static/js/example.js

document.addEventListener('DOMContentLoaded', function () {
    const baseUrl = isOvsa ? '/lwadata-query' : '';

    const startInput = document.getElementById('start');
    const endInput = document.getElementById('end');
    const cadenceInput = document.getElementById('cadence');
    let movieOffsetDays = 0;
    let queryVersion = 0;

    const now = new Date();
    const past = new Date();
    past.setDate(now.getDate() - 7);

    const formatDate = (date) => date.toISOString().slice(0, 19);

    startInput.value = formatDate(past);
    endInput.value = formatDate(now);

    flatpickr(".datetime-picker", {
        enableTime: true,
        dateFormat: "Y-m-d\\TH:i:S",
        allowInput: true,
        time_24hr: true,
    });


    function updateFileList(elementId, files) {
        const listElement = document.getElementById(elementId);
        listElement.innerHTML = '';
        files.forEach(file => {
            const option = document.createElement('option');
            option.value = file;
            option.textContent = file;
            listElement.appendChild(option);
        });
    }

    // function selectAll(listId) {
    //     const list = document.getElementById(listId);
    //     for (let i = 0; i < list.options.length; i++) {
    //         list.options[i].selected = true;
    //     }
    //     // Force redraw (needed in some browsers like Chrome)
    //     list.blur();  // remove focus
    //     list.focus(); // re-focus triggers redraw of grey highlighting
    // }

    function updateSpecAndMovie(baseStart, offsetDays, thisQuery = null) {
        const dateStr = baseStart.slice(0, 10);
        const baseDate = new Date(`${dateStr}T00:00:00`);
        baseDate.setUTCDate(baseDate.getUTCDate() + offsetDays);
        const newDateStr = baseDate.toISOString().slice(0, 10);
        const shiftedStart = `${newDateStr}T12:00:00`;

        const formData = new FormData();
        formData.append("start", shiftedStart);

        fetch(`${baseUrl}/api/flare/spec_movie`, {
            method: 'POST',
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (thisQuery !== null && thisQuery !== queryVersion) return;

            const movieContainer = document.getElementById("movie-container");
            const moviePlayer = document.getElementById("movie-player");
            const movieSource = document.getElementById("movie-player-source");
            const movieMessage = document.getElementById("movie-message");
            const specImage = document.getElementById("spec-preview");
            const specMessage = document.getElementById("spec-message");

            if (data.movie_path) {
                movieSource.src = data.movie_path;
                moviePlayer.load();
                moviePlayer.style.display = "block";
                movieMessage.style.display = "none";
            } else {
                moviePlayer.style.display = "none";
                movieMessage.style.display = "block";
            }

            if (data.spec_png_path) {
                specImage.src = data.spec_png_path;
                specImage.style.display = "block";
                specMessage.style.display = "none";
            } else {
                specImage.style.display = "none";
                specMessage.style.display = "block";
            }

            movieContainer.style.display = "block";
        });
    }

    function setupGenerateAndDownloadButtons(bundleType) {
        const generateBtn = document.getElementById(`generate-${bundleType}`);
        const downloadBtn = document.getElementById(`download-${bundleType}`);

        generateBtn.onclick = () => {
            // const listId = bundleType === 'spec_fits' ? 'spec-list' :
            //                bundleType === 'slow_lev1' ? 'image-lev1-list' :
            //                bundleType === 'slow_lev15' ? 'image-lev15-list';
            const listId = bundleType === 'spec_fits' ? 'spec-list' :
                           bundleType === 'slow_lev1' ? 'image-lev1-list' :
                           'image-lev15-list';

            const listElement = document.getElementById(listId);
            let selectedFiles = Array.from(listElement.selectedOptions).map(opt => opt.value);
            // If none selected, fallback to all
            if (selectedFiles.length === 0) {
                selectedFiles = Array.from(listElement.options).map(opt => opt.value);
            }

            const formData = new FormData();
            formData.append('start', startInput.value);
            formData.append('end', endInput.value);
            const cadence = cadenceInput.value;
            if (cadence) formData.append('cadence', cadence);

            formData.append('selected_files', JSON.stringify(selectedFiles));

            downloadBtn.disabled = true;
            fetch(`${baseUrl}/generate_bundle/${bundleType}`, {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                const archiveName = data.archive_name;
                downloadBtn.dataset.archiveName = archiveName;
                downloadBtn.disabled = false;
            })
            .catch(() => {
                alert(`Failed to generate ${bundleType} bundle.`);
            });
        };


        downloadBtn.onclick = () => {
            const archiveName = downloadBtn.dataset.archiveName;
            if (archiveName) {
                window.location.href = `${baseUrl}/download_ready_bundle/${archiveName}`;
            }
        };
    }

    function queryAndUpdate() {
        const thisQuery = ++queryVersion;

        const start = startInput.value;
        const end = endInput.value;
        const cadence = cadenceInput.value;

        const formData = new FormData();
        formData.append('start', start);
        formData.append('end', end);
        if (cadence) {
            formData.append('cadence', cadence);
        }

        fetch(`${baseUrl}/api/flare/query`, {
            method: 'POST',
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (thisQuery !== queryVersion) return;

            updateFileList('spec-list', data.spec_fits);
            updateFileList('image-lev1-list', data.slow_lev1);
            updateFileList('image-lev15-list', data.slow_lev15);

            setupGenerateAndDownloadButtons('spec_fits');
            setupGenerateAndDownloadButtons('slow_lev1');
            setupGenerateAndDownloadButtons('slow_lev15');

            movieOffsetDays = 0;
            updateSpecAndMovie(start, movieOffsetDays, thisQuery);

            const plotFormData = new FormData();
            plotFormData.append('start', start);
            plotFormData.append('end', end);
            if (cadence) {
                plotFormData.append('cadence', cadence);
            }

            fetch(`${baseUrl}/plot`, {
                method: 'POST',
                body: plotFormData
            })
            .then(res => res.json())
            .then(result => {
                if (thisQuery !== queryVersion) return;
                const plotJSON = JSON.parse(result.plot);
                Plotly.newPlot('plot-container', plotJSON.data, plotJSON.layout);
            });
        });
    }

    // document.getElementById('query-btn').addEventListener('click', function (e) {
    //     e.preventDefault();
    //     queryAndUpdate();
    // });

    const queryBtn = document.getElementById('query-btn');
    if (queryBtn) {
        // Remove all previous listeners to be safe
        queryBtn.replaceWith(queryBtn.cloneNode(true));
        const newQueryBtn = document.getElementById('query-btn');
        newQueryBtn.addEventListener('click', function (e) {
            console.log("Binding click");
            e.preventDefault();
            queryAndUpdate();
        });
    }

    document.getElementById('plus1day').addEventListener('click', () => {
        movieOffsetDays += 1;
        const baseStart = startInput.value;
        updateSpecAndMovie(baseStart, movieOffsetDays);
    });

    document.getElementById('minus1day').addEventListener('click', () => {
        movieOffsetDays -= 1;
        const baseStart = startInput.value;
        updateSpecAndMovie(baseStart, movieOffsetDays);
    });

    // Add handlers for both level1 and level1.5 movie generation
    ['slow_lev1', 'slow_lev15'].forEach(bundleType => {
        const btnId = `generate-movie-${bundleType}`;
        const listId = bundleType === 'slow_lev1' ? 'image-lev1-list' : 'image-lev15-list';
        const movieBtn = document.getElementById(btnId);

        if (movieBtn) {
            movieBtn.onclick = () => {
                const listElement = document.getElementById(listId);
                let selectedFiles = Array.from(listElement.selectedOptions).map(opt => opt.value);
                if (selectedFiles.length === 0) {
                    selectedFiles = Array.from(listElement.options).map(opt => opt.value);
                }

                const formData = new FormData();
                formData.append('selected_files', JSON.stringify(selectedFiles));

                fetch(`${baseUrl}/generate_html_movie`, {
                    method: 'POST',
                    body: formData
                })
                .then(res => res.json())
                .then(data => {
                    if (data.movie_url) {
                        window.open(data.movie_url, '_blank');
                    } else {
                        alert("Movie URL not returned.");
                    }
                })
                .catch(() => {
                    alert("Failed to generate movie HTML.");
                });
            };
        } else {
            console.warn(`Movie button ${btnId} not found`);
        }
    });
    

});
