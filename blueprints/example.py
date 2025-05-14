import numpy as np
import pandas as pd
import os
import mysql.connector
from flask import Flask, Blueprint, render_template, request, jsonify, url_for, redirect, send_file
import plotly
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import re
import socket
import json
import requests
from pathlib import Path
import subprocess
import tempfile
from astropy.time import Time
from datetime import datetime, timedelta
from glob import glob
import shutil
import os
from imageio import imread

##=========================
example = Blueprint('example', __name__, template_folder='templates')

##=========================
def create_lwa_query_db_connection():
    return mysql.connector.connect(
        host=os.getenv('FLARE_DB_HOST'),
        database='lwa_metadata_query',
        user=os.getenv('FLARE_DB_USER'),
        password=os.getenv('FLARE_DB_PASSWORD')
    )

##=========================
def get_lwa_file_lists_from_mysql(start_utc, end_utc):
    start = Time(start_utc).datetime
    end = Time(end_utc).datetime
    connection = create_lwa_query_db_connection()
    cursor = connection.cursor()
    query = """
        SELECT file_path, obs_time FROM {table}
        WHERE obs_time BETWEEN %s AND %s
        ORDER BY obs_time
    """
    # tables = {
    #     'fast_hdf': 'lwa_fast_hdf_files',
    #     'slow_hdf': 'lwa_slow_hdf_files',
    #     'spec_fits': 'lwa_spec_fits_files'
    # }
    tables = {
        'spec_fits': 'lwa_spec_fits_files',
        'slow_lev1': 'lwa_slow_lev1_hdf_files',
        'slow_lev15': 'lwa_slow_lev15_hdf_files'
    }
    file_lists = {}
    obs_times = {}
    for file_type, table in tables.items():
        cursor.execute(query.format(table=table), (start, end))
        rows = cursor.fetchall()
        file_lists[file_type] = [row[0] for row in rows]
        obs_times[file_type] = [row[1] for row in rows]
    cursor.close()
    connection.close()
    return file_lists, obs_times

##=========================
def convert_local_to_urls(files_path):
    """
    Convert local HDF paths to public HTTPS URLs.

    Parameters:
        files_path (list): List of local HDF file paths (str)

    Returns:
        list: List of converted HTTPS URLs
    """
    urls = []
    for file_path in files_path:
        if file_path.startswith("/nas7/ovro-lwa-data/hdf/"):
            url = file_path.replace("/nas7/ovro-lwa-data/hdf/", "https://ovsa.njit.edu/lwadata3/hdf/")
        elif file_path.startswith("/nas6/ovro-lwa-data/hdf/"):
            url = file_path.replace("/nas6/ovro-lwa-data/hdf/", "https://ovsa.njit.edu/lwadata2/hdf/")
        elif file_path.startswith("/common/lwa/spec_v2/fits/"):
            filename = os.path.basename(file_path)
            url = f"https://ovsa.njit.edu/lwa/extm/fits/{filename}"
        else:
            url = file_path  # fallback
        urls.append(url)
    return urls

##=========================
def convert_local_to_filename(files_path):
    """
    Convert local HDF paths to filename only.

    Parameters:
        files_path (list): List of local HDF file paths (str)

    Returns:
        list: List of converted file names
    """
    return [os.path.basename(path) for path in files_path]

##=========================
# output_name = "slow_hdf_movie.mp4"
def generate_movie_from_pngs(png_files, output_name=None):
    if not png_files:
        return None

    if not output_name:
        date_str = os.path.basename(png_files[0]).split("T")[0].split('.')[-1].replace("-", "")
        output_name = f"slow_hdf_movie_{date_str}_sub.mp4"

    temp_dir = tempfile.mkdtemp()
    try:
        # Symlink all PNGs into temp dir with simple names: 0001.png, 0002.png...
        for i, f in enumerate(sorted(png_files)):
            link_name = os.path.join(temp_dir, f"{i:04d}.png")
            os.symlink(f, link_name)

        output_path = os.path.join("static", "movies", output_name)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-framerate", "6",
            "-i", os.path.join(temp_dir, "%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            output_path
        ]
        subprocess.run(cmd, check=True)
        return "/" + output_path
    except Exception as e:
        print("Movie generation failed:", e)
        return None
    finally:
        shutil.rmtree(temp_dir)

##=========================
def convert_slow_hdf_to_existing_png(hdf_list):
    """
    Convert each .hdf path (lev1 or lev15) to its corresponding .png path by timestamp match,
    and return only those that actually exist on disk.

    Parameters:
        hdf_list (list): List of full paths to .hdf files

    Returns:
        List of existing .png file paths
    """
    png_list = []
    for hdf_path in hdf_list:
        try:
            hdf_filename = os.path.basename(hdf_path)
            # Extract timestamp part
            if "T" in hdf_filename and hdf_filename.endswith(".hdf"):
                timestamp_part = hdf_filename.split("T")[1].split("Z")[0]  # e.g., "123456"
                date_part = hdf_filename.split("T")[0].split('.')[-1]      # e.g., "2025-05-10"
                yyyy, mm, dd = date_part.split('-')
            else:
                continue  # skip if format unexpected
            # Reconstruct PNG filename
            # Example: ovro-lwa-352.synop_mfs_10s.2025-05-10T123456Z.image_I.png
            prefix = "ovro-lwa-352.synop_mfs_10s"
            png_filename = f"{prefix}.{date_part}T{timestamp_part}Z.image_I.png"
            # png_filename = hdf_filename.replace('.lev1.5_', '.synop_').replace('.hdf', '.png')
            png_path = f"/common/webplots/lwa-data/qlook_images/slow/synop/{yyyy}/{mm}/{dd}/{png_filename}"
            if os.path.exists(png_path):
                png_list.append(png_path)
        except Exception as e:
            print(f"Error processing {hdf_path}: {e}")
            continue
    return png_list
# png_files = convert_slow_hdf_to_existing_png(slow_hdf_files)


##=========================
def convert_png_to_urls(png_paths):
    """
    Convert full PNG file paths to public HTTPS URLs based on path pattern.

    Parameters:
        png_paths (list): Full local PNG file paths (e.g., /common/webplots/.../png)

    Returns:
        List of HTTPS URLs pointing to each image.
    """
    urls = []
    for png_path in sorted(png_paths):
        try:
            png_filename = os.path.basename(png_path)

            # Extract date/time string for folder and filename
            timestamp_part = png_filename.split("T")[1].split("Z")[0]  # e.g., "123456"
            date_str = png_filename.split("T")[0].split(".")[-1]  # e.g., 2025-05-10
            yyyy, mm, dd = date_str.split("-")
            url = f"https://ovsa.njit.edu/lwa-data/qlook_images/slow/synop/{yyyy}/{mm}/{dd}/{png_filename}"
            urls.append(url)
        except Exception as e:
            print(f"Failed to convert {png_path} to URL: {e}")
            continue
    return urls


##=========================
def filter_files_by_cadence(times, files, cadence_sec):
    """
    Filter (time, file) pairs to enforce a minimum time spacing (cadence).

    Parameters:
        times (list of datetime): observation times
        files (list of str): file paths (must match 1-to-1 with times)
        cadence_sec (int): minimum time spacing in seconds

    Returns:
        (filtered_times, filtered_files)
    """
    if not times or not files or len(times) != len(files):
        return times, files  # return original if mismatch

    filtered_times = [times[0]]
    filtered_files = [files[0]]
    last_time = times[0]

    for i in range(1, len(times)):
        if (times[i] - last_time).total_seconds() >= cadence_sec:
            filtered_times.append(times[i])
            filtered_files.append(files[i])
            last_time = times[i]

    return filtered_times, filtered_files


##=========================
@example.route("/api/flare/query", methods=['POST'])
def get_lwafilelist_from_database():

    start = request.form['start']
    end = request.form['end']
    cadence = request.form.get('cadence', None)
    cadence_sec = int(cadence) if cadence else None
    print("qqq,cadence_sec", cadence_sec)
    if not start or not end:
        raise ValueError("Start and end times are required.")

    file_lists, obs_times = get_lwa_file_lists_from_mysql(start, end)

    if cadence_sec:
        for key in ['slow_lev1', 'slow_lev15']:
            obs_times[key], file_lists[key] = filter_files_by_cadence(
                obs_times[key], file_lists[key], cadence_sec
            )

    print(f"Query: Found {len(file_lists['spec_fits'])} spec_fits files")
    print(f"Query: Found {len(file_lists['slow_lev1'])} slow_lev1_hdf files")
    print(f"Query: Found {len(file_lists['slow_lev15'])} slow_lev15_hdf files")

    # # Convert local HDF paths to public HTTPS URLs
    # file_lists['spec_fits']   = convert_local_to_urls(file_lists['spec_fits'])
    # file_lists['slow_lev1']   = convert_local_to_urls(file_lists['slow_lev1'])
    # file_lists['slow_lev15']  = convert_local_to_urls(file_lists['slow_lev15'])

    # Convert local HDF paths to file names only
    file_lists['spec_fits']   = convert_local_to_filename(file_lists['spec_fits'])
    file_lists['slow_lev1']   = convert_local_to_filename(file_lists['slow_lev1'])
    file_lists['slow_lev15']  = convert_local_to_filename(file_lists['slow_lev15'])

    return jsonify({
        "spec_fits": file_lists['spec_fits'],
        "slow_lev1": file_lists['slow_lev1'],
        "slow_lev15": file_lists['slow_lev15']
    })


# #=========================
def generate_html_movie_from_png(png_paths):
    """
    Generate an HTML movie file from a list of PNG paths using a JavaScript-based animation template.

    Parameters:
        png_paths (list): List of full PNG file paths

    Returns:
        str: Public URL of the generated HTML movie
    """
    if not png_paths:
        raise ValueError("No PNG files provided.")

    try:
        png_paths = sorted(png_paths)[:20]  # Limit to first 200 frames
        first_png = png_paths[0]
        if "T" not in first_png:
            raise ValueError("Filename missing timestamp.")

        # Extract date/time string for folder and filename
        timestamp_part = first_png.split("T")[1].split("Z")[0]  # e.g., "123456"
        date_str = first_png.split("T")[0].split(".")[-1]  # e.g., 2025-05-10
        yyyy, mm, dd = date_str.split("-")
        output_name = f"movie_{date_str}T{timestamp_part}Z.html"
        # output_dir = f"/common/webplots/lwa-data/qlook_images/slow/synop/{yyyy}/{mm}/{dd}"
        # os.makedirs(output_dir, exist_ok=True)
        output_dir = f"/common/webplots/lwa-data/tests/test-movie-can-rm-anytime/"
        html_path = os.path.join(output_dir, output_name)
        print(f"???html_path: {html_path}")

        # Read image dimensions
        img = imread(first_png)
        ysize, xsize = img.shape[:2]
        if xsize > 1125:
            xfsize = xsize * 3 // 4
            yfsize = ysize * 3 // 4
        else:
            xfsize = xsize
            yfsize = ysize

        # Read template
        # template_path = "/nas5/ovro-lwa-data/beam/software/html_movie_example.html"
        template_path = "/data1/xychen/flaskenv/html_movie_example.html"
        if not os.path.exists(template_path):
            raise FileNotFoundError("Template HTML file not found.")
        with open(template_path, "r") as f:
            lines = f.readlines()

        new_lines = []
        inserted_url_path = False

        for i, line in enumerate(lines):
            if "<script" in line and not inserted_url_path:
                new_lines.append(line)
                new_lines.append(f'var url_path = "https://ovsa.njit.edu/lwa-data/qlook_images/slow/synop/{yyyy}/{mm}/{dd}";\n')
                inserted_url_path = True
            elif "var imax" in line:
                new_lines.append(f"var imax = {len(png_paths)};\n")
            elif "var iwidth" in line:
                new_lines.append(f"var iwidth = {xsize}, iheight = {ysize};\n")
            elif "NAME=animation" in line:
                new_lines.append(f'<img NAME=animation ALT="FRAME" width={xfsize} height={yfsize}>\n')
            elif "urls[" in line:
                break  # stop before appending URL list
            else:
                new_lines.append(line)

        # Append image URLs
        for i, path in enumerate(png_paths):
            fname = os.path.basename(path)
            new_lines.append(f'urls[{i}]=url_path+"/{fname}";\n')

        # Find remaining lines after image list (past 2nd "urls[" line)
        post_lines = []
        urls_found = 0
        for line in lines:
            if "urls[" in line:
                urls_found += 1
                if urls_found == 2:
                    post_lines.append(line)
            elif urls_found >= 2:
                post_lines.append(line)

        new_lines.extend(post_lines)

        # Write HTML file
        with open(html_path, "w") as f:
            f.writelines(new_lines)

        movie_url = f"https://ovsa.njit.edu/lwa-data/tests/test-movie-can-rm-anytime/{output_name}"

        # Return URL
        return movie_url

    except Exception as e:
        raise RuntimeError(f"Failed to generate HTML movie: {e}")


#=========================works
@example.route('/generate_html_movie', methods=['POST'])
def generate_html_movie():
    selected_files_json = request.form.get('selected_files', '')
    if not selected_files_json:
        return "No files selected", 400

    try:
        selected_files = json.loads(selected_files_json)
    except Exception as e:
        return f"Invalid JSON: {e}", 400
    print("??selected_files", selected_files[0])

    # selected_files eg. 'ovro-lwa-352.lev1_mfs_10s.2025-05-10T00000Z.image_l.hdf'
    # png file eg. 'ovro-lwa-352.synop_mfs_10s.2025-05-10T000208Z.image_I.png'
    try:
        # ##===== exist movie.html
        # first_file = selected_files[0]
        # date_str = first_file.split("T")[0].split(".")[-1]  # e.g., 2025-05-10
        # yyyy, mm, dd = date_str.split("-")
        # movie_url = f"https://ovsa.njit.edu/lwa-data/qlook_images/slow/synop/{yyyy}/{mm}/{dd}/movie_{date_str}.html"

        ##===== generate a new movie.html
        png_files = convert_slow_hdf_to_existing_png(selected_files)
        print(f"png_files: {png_files[:2]}")
        movie_url = generate_html_movie_from_png(png_files)
        print("??movie_url", movie_url)
        print(f"Generate_html_movie: success! {movie_url}")

        return jsonify({"movie_url": movie_url})
    except Exception as e:
        return f"Could not construct movie path: {e}", 500


##=========================
def get_spec_and_movie_paths(slow_hdf_files):
    png_files = convert_slow_hdf_to_existing_png(slow_hdf_files)
    movie_path = generate_movie_from_pngs(png_files) if png_files else None
    # if movie_path:
    #     cache_buster = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    #     movie_path += f"?v={cache_buster}"
    try:
        date_str = os.path.basename(png_files[0]).split("T")[0].split('.')[-1].replace("-", "")
        spec_png = f"https://ovsa.njit.edu/lwa/extm/daily/{date_str}.png"
    except Exception as e:
        spec_png = None
        print("Spec image link generation failed:", e)
    return spec_png, movie_path

##=========================
@example.route("/api/flare/spec_movie", methods=['POST'])
def get_lwa_spec_movie_from_database():
    start = request.form['start']
    if not start:
        raise ValueError("Start time is required.")
    print("start111", start)
    # ## Method 1: Generate image movies for the given time range
    # start_time = Time(start).datetime
    # end_time = start_time + timedelta(hours=2)
    # file_lists, _ = get_lwa_file_lists_from_mysql(start_time.isoformat(), end_time.isoformat())
    # slow_hdf_files = file_lists['slow_lev15']#)[:20]
    # spec_png_path, movie_path = get_spec_and_movie_paths(slow_hdf_files)

    start_time = Time(start).datetime
    date_str = start_time.strftime("%Y%m%d")
    movie_filename = f"slow_hdf_movie_{date_str}.mp4"
    movie_path_local = os.path.join("static", "movies", movie_filename)

    if os.path.exists(movie_path_local):
        # Method 2: Return the existing movie if available
        movie_path = f"/static/movies/{movie_filename}"
        spec_png_path = f"https://ovsa.njit.edu/lwa/extm/daily/{date_str}.png"
    else:
        # Method 1: Generate movie dynamically from PNGs
        end_time = start_time + timedelta(hours=6)
        file_lists, _ = get_lwa_file_lists_from_mysql(start_time.isoformat(), end_time.isoformat())
        slow_hdf_files = file_lists['slow_lev15']#)[:20]
        spec_png_path, movie_path = get_spec_and_movie_paths(slow_hdf_files)
    ##
    print("spec_png_path", spec_png_path)
    print("movie_path", movie_path)
    return jsonify({
        "movie_path": movie_path,
        "spec_png_path": spec_png_path
    })



# ##=========================
'''Several method to downsample times
'''
def downsample(times, max_points=1000):
    if len(times) <= max_points:
        return times
    step = max(1, len(times) // max_points)
    return times[::step]

def bin_times(times, freq='1min'):
    """Convert a list of datetime objects to start times of bins."""
    if not times:
        return []
    df = pd.DataFrame({'time': pd.to_datetime(times)})
    df['binned'] = df['time'].dt.floor(freq)
    return df['binned'].drop_duplicates().tolist()

def segment_continuous_times(times, gap='1min'):
    """
    Segments input times into continuous blocks where time difference <= gap.
    Useful for Plotly line plotting with gaps.

    Parameters:
        times (list): List of datetime.datetime objects
        gap (str): A pandas-style time string (e.g., '1min', '30s')

    Returns:
        List of lists, each inner list is a continuous time segment
    """
    if not times:
        return []

    gap_td = pd.to_timedelta(gap)
    times_sorted = sorted(pd.to_datetime(times))

    segments = []
    current_segment = [times_sorted[0]]

    for t1, t2 in zip(times_sorted[:-1], times_sorted[1:]):
        if t2 - t1 <= gap_td:
            current_segment.append(t2)
        else:
            segments.append(current_segment)
            current_segment = [t2]

    segments.append(current_segment)
    return segments

def compress_time_segments(times, max_gap_seconds=60):
    """
    Reduce a list of datetime points to segments with only start and end time
    if points are within a max_gap.

    Parameters:
        times (list): List of datetime.datetime objects
        max_gap_seconds (int): Maximum gap between consecutive points to consider continuous

    Returns:
        List of (start, end) tuples representing continuous spans
    """
    if not times:
        return []

    times = sorted(times)
    max_gap = timedelta(seconds=max_gap_seconds)

    segments = []
    start = times[0]
    prev = times[0]

    for t in times[1:]:
        if t - prev > max_gap:
            segments.append((start, prev))
            start = t
        prev = t

    segments.append((start, prev))
    return segments

color_map = {
    'spec_fits': '#1f77b4',  # muted blue
    'slow_lev1':  '#ff7f0e',  # safety orange
    'slow_lev15':  '#2ca02c'   # green
}

# ##=========================
@example.route('/plot', methods=['POST'])
def plot():
    start = request.form['start']
    end = request.form['end']
    # cadence = request.form.get('cadence')
    # cadence_sec = int(cadence) if cadence and cadence.strip().isdigit() else None
    cadence = request.form.get('cadence', None)
    cadence_sec = int(cadence) if cadence else None
    print("ppp, cadence_sec", cadence_sec)

    try:
        start = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S") - timedelta(days=0)
        end = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S") + timedelta(days=0)
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    if start > end:
        return jsonify({'error': 'End date must be after start date'}), 400

    file_lists, obs_times = get_lwa_file_lists_from_mysql(Time(start).isot, Time(end).isot)
    if cadence_sec:
        for key in ['slow_lev1', 'slow_lev15']:
            obs_times[key], file_lists[key] = filter_files_by_cadence(
                obs_times[key], file_lists[key], cadence_sec
            )

    fig = go.Figure()
    labels = ['spec_fits', 'slow_lev1', 'slow_lev15']
    labels_fig = ['spec_fits', 'image_lev1', 'image_lev15']

    for i, (label, label_fig) in enumerate(zip(labels, labels_fig)):
    # for ll, label in enumerate(labels):

        times = obs_times.get(label, [])
        y_values = [label_fig] * len(times)
        label_with_count = f"N({label_fig}) = {len(times)}" if times else f"N({label_fig}) = 0"

        if label == 'spec_fits' or not times:
            # Ensure a trace is added even if there are no files
            fig.add_trace(go.Scatter(
                x=times if times else [None],
                y=y_values if times else [label_fig],
                mode='markers',
                marker=dict(size=8, color=color_map[label]),
                name=label_with_count,
                showlegend=True# if times else False
            ))
        else:
            if label == 'slow_lev1':
                segments = compress_time_segments(times, max_gap_seconds=600)#180
            else:
                segments = compress_time_segments(times, max_gap_seconds=600)

            show_legend = True
            for i_st, i_ed in segments:
                fig.add_trace(go.Scatter(
                    x=[i_st, i_ed],
                    y=[label_fig, label_fig],
                    mode='lines',
                    line=dict(width=15, color=color_map[label]),
                    name=label_with_count,
                    showlegend=show_legend
                ))
                show_legend = False

    print(f"Plot Data Availability...")

    fig.update_layout(
        title='Data Availability',
        xaxis_title='',#'Time'
        yaxis_title='',
        xaxis=dict(tickfont=dict(size=16), title_font=dict(size=16)),
        yaxis=dict(categoryorder='array', categoryarray=labels_fig, tickfont=dict(size=16), title_font=dict(size=16)),
        legend=dict(font=dict(size=16)),
        height=400
    )

    return jsonify({
        'plot': pio.to_json(fig)
    })



# ##=========================
def extract_timestamp_from_filename(filename):
    """
    Extract YYYY-MM-DDTHHMMSSZ-like timestamp from filename and convert to YYYYMMDDTHHMMSS
    """
    match = re.search(r"\d{4}-\d{2}-\d{2}T\d{6}", filename)
    if match:
        return match.group(0).replace("-", "").replace(":", "")
    else:
        return "UNKNOWN"


@example.route('/generate_bundle/<bundle_type>', methods=['POST'])
def generate_data_bundle(bundle_type):
    start = request.form.get('start')
    end = request.form.get('end')

    cadence = request.form.get('cadence', None)
    cadence_sec = int(cadence) if cadence else None

    if not start or not end:
        return "Start and end parameters are required", 400

    file_lists, obs_times = get_lwa_file_lists_from_mysql(start, end)

    if bundle_type not in file_lists:
        return f"Invalid bundle type: {bundle_type}", 400

    if cadence_sec and bundle_type in ['slow_lev1', 'slow_lev15']:
        obs_times[bundle_type], file_lists[bundle_type] = filter_files_by_cadence(
            obs_times[bundle_type], file_lists[bundle_type], cadence_sec
        )

    # for selected_files
    selected_files_json = request.form.get('selected_files')
    if selected_files_json:
        try:
            selected_files = set(json.loads(selected_files_json))
            file_paths = [f for f in file_lists[bundle_type] if os.path.basename(f) in selected_files]
        except Exception as e:
            return f"Invalid selected_files format: {e}", 400
    else:
        file_paths = file_lists[bundle_type]

    # file_paths = file_lists[bundle_type]
    if not file_paths:
        return f"No files found for {bundle_type}", 404

    if len(file_paths) > 10:
        file_paths = file_paths[:10]
        print(f"Limiting download to first 1000 files out of {len(file_paths)}")

    bundle_names = {
        'spec_fits': 'ovro-lwa-spec',
        'slow_lev1': 'ovro-lwa-image-lev1',
        'slow_lev15': 'ovro-lwa-image-lev15'
    }
    start_time_str = extract_timestamp_from_filename(os.path.basename(file_paths[0]))
    end_time_str = extract_timestamp_from_filename(os.path.basename(file_paths[-1]))
    cadence_suffix = f"_cad{cadence_sec}s" if cadence_sec else ""

    archive_label = bundle_names.get(bundle_type, bundle_type)
    archive_filename = f"{archive_label}_{start_time_str}_{end_time_str}{cadence_suffix}.tar.gz"
    # Create a permanent bundle output path
    bundle_dir = "/data1/xychen/flaskenv/lwa_data_query_request"
    os.makedirs(bundle_dir, exist_ok=True)
    # archivse_path = os.path.join(bundle_dir, f"{bundle_type}_{start_time_str}_{end_time_str}.tar.gz")
    archive_path = os.path.join(bundle_dir, archive_filename)

    # Create .tar
    if not os.path.exists(archive_path):
        with tempfile.TemporaryDirectory() as temp_dir:
            for path in file_paths:
                if os.path.exists(path):
                    shutil.copy(path, temp_dir)
            shutil.make_archive(
                base_name=archive_path.replace(".tar.gz", ""),
                format="gztar",
                root_dir=temp_dir
            )
    print(f"Generate bundle for {bundle_type} from {start} to {end}")
    return jsonify({"archive_name": os.path.basename(archive_path)})


# ##=========================
@example.route('/download_ready_bundle/<archive_name>', methods=['GET'])
def download_ready_bundle(archive_name):
    bundle_dir = "/data1/xychen/flaskenv/lwa_data_query_request"
    archive_path = os.path.join(bundle_dir, archive_name)
    if os.path.exists(archive_path):
        return send_file(archive_path, as_attachment=True, download_name=archive_name)
    else:
        return f"{archive_name} not found", 404


# ##=========================
@example.route("/")
def render_example_paper():
    hostname = socket.gethostname()
    return render_template('index.html', result=[], plot_html_ID=None, hostname=hostname)