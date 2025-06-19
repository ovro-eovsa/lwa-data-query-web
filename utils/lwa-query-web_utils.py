# python lwa-query-web_utils.py --gen movie-daily --start 2025-04-25 --end 2025-05-01
# python lwa-query-web_utils.py --gen movie-daily --start 2025-04-25 --end 2025-05-01 --out /tmp/movies
# python lwa-query-web_utils.py --gen movie-trange --start "2025-04-25 12:00:00" --end "2025-04-26 03:00:00" --output-name movie.mp4
# python lwa-query-web_utils.py --gen data-files-counts --start 2025-04-25T00:00:00 --end 2025-05-01T00:00:00 --image-type mfs
##du -h /common/webplots/lwa-data/qlook_daily/movies/*.mp4
import mysql.connector
import os
from glob import glob
from datetime import datetime, timedelta
import subprocess
import tempfile
import shutil
import argparse
from astropy.time import Time

##=========================connect to database
def create_lwa_query_db_connection():
    return mysql.connector.connect(
        host=os.getenv('FLARE_DB_HOST'),
        database='lwa_metadata_query',#os.getenv('FLARE_DB_DATABASE'),
        user=os.getenv('FLARE_DB_USER'),
        password=os.getenv('FLARE_DB_PASSWORD')
    )
# connection = create_lwa_query_db_connection()
# cursor = connection.cursor()

##=========================connect to database
def get_lwa_file_lists_from_mysql(start_utc, end_utc, image_type="mfs"):
    start = Time(start_utc).datetime
    end = Time(end_utc).datetime
    # Choose table based on image_type
    if image_type == "mfs":
        tables = {
            'spec_fits': 'lwa_spec_fits_files',
            'slow_lev1': 'lwa_slow_mfs_lev1_hdf_files',
            'slow_lev15': 'lwa_slow_mfs_lev15_hdf_files'
        }
    elif image_type == "fch":
        tables = {
            'spec_fits': 'lwa_spec_fits_files',
            'slow_lev1': 'lwa_slow_fch_lev1_hdf_files',
            'slow_lev15': 'lwa_slow_fch_lev15_hdf_files'
        }
    else:
        raise ValueError(f"Unsupported image_type: {image_type}")
    # Connection
    connection = create_lwa_query_db_connection()
    cursor = connection.cursor()
    query_spec = """
        SELECT file_path, start_time, end_time FROM lwa_spec_fits_files
        WHERE start_time <= %s AND end_time >= %s
        ORDER BY start_time
    """
    query_img = """
        SELECT file_path, obs_time FROM {table}
        WHERE obs_time BETWEEN %s AND %s
        ORDER BY obs_time
    """
    file_lists = {}
    obs_times = {}
    for file_type, table in tables.items():
        if file_type == 'spec_fits':
            cursor.execute(query_spec, (end, start))
            rows = cursor.fetchall()
            file_lists[file_type] = [row[0] for row in rows]
            obs_times[file_type] = [(row[1], row[2]) for row in rows]
        else:
            cursor.execute(query_img.format(table=table), (start, end))
            rows = cursor.fetchall()
            file_lists[file_type] = [row[0] for row in rows]
            obs_times[file_type] = [row[1] for row in rows]
    cursor.close()
    connection.close()
    return file_lists, obs_times
# Example usage:
# file_lists, obs_times = get_lwa_file_lists_from_mysql("2025-04-01T00:00:00", "2025-05-01T00:00:00", image_type="mfs")

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
            png_path = f"{lwadata_dir}/qlook_images/slow/synop/{yyyy}/{mm}/{dd}/{png_filename}"
            if os.path.exists(png_path):
                png_list.append(png_path)
        except Exception as e:
            logger.warning("Error processing %s: %s", hdf_path, e)
            continue
    return png_list

##=========================
def gen_daily_movies_from_date_range(start_date_str, end_date_str, save_path='/common/webplots/lwa-data/qlook_daily/movies/'):
    """
    Given a date range in 'YYYY-MM-DD' format, find PNGs under the
    corresponding LWA synoptic image directory and generate a movie per day,
    restricted to 12:00 of the day to 03:00 of the next day.
    Will be uploaded to the public web folder.
    Movie files will be re-written.

    Args:
        start_date_str (str): start date in 'YYYY-MM-DD'
        end_date_str (str): end date in 'YYYY-MM-DD'
        save_path (str): directory where movies are saved

    Returns:
        dict: {date_str: movie_relative_path or None}
    """
    results = {}
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        current_date = start_date

        while current_date <= end_date:
            date_str = current_date.strftime("%Y-%m-%d")
            yyyy, mm, dd = current_date.strftime("%Y"), current_date.strftime("%m"), current_date.strftime("%d")
            img_dir = f"/common/webplots/lwa-data/qlook_images/slow/synop/{yyyy}/{mm}/{dd}"
            all_png_files = sorted(glob(os.path.join(img_dir, "*.png")))

            if not all_png_files:
                print(f"[{date_str}] No PNG files found.")
                results[date_str] = None
                current_date += timedelta(days=1)
                continue

            start_time = datetime.combine(current_date, datetime.strptime("12:00:00", "%H:%M:%S").time())
            end_time = datetime.combine(current_date + timedelta(days=1), datetime.strptime("03:00:00", "%H:%M:%S").time())

            def extract_timestamp(path):
                base = os.path.basename(path)
                try:
                    tstr = base.split("T")[1][:6]  # 'HHMMSS'
                    dstr = base.split("T")[0].split(".")[-1]  # 'YYYY-MM-DD'
                    return datetime.strptime(dstr + tstr, "%Y-%m-%d%H%M%S")
                except Exception:
                    return None

            ## support >python3.8
            # png_files = [f for f in all_png_files if (ts := extract_timestamp(f)) and start_time <= ts <= end_time]
            png_files = []
            for f in all_png_files:
                ts = extract_timestamp(f)
                if ts and start_time <= ts <= end_time:
                    png_files.append(f)

            if not png_files:
                print(f"[{date_str}] No PNGs in 12:00-03:00 window.")
                results[date_str] = None
                current_date += timedelta(days=1)
                continue

            print(f"[{date_str}] {len(png_files)} PNGs in time window.")
            temp_dir = tempfile.mkdtemp()
            print(temp_dir)

            try:
                # It creates temporary symbolic links to those files in a temp directory:                
                for i, f in enumerate(png_files):
                    os.symlink(f, os.path.join(temp_dir, f"{i:04d}.png"))

                # output_name = f"slow_image_movie_{yyyy}{mm}{dd}.mp4"
                output_name = f"ovro-lwa-352.synop_mfs_image_I_movie_{yyyy}{mm}{dd}.mp4"
                output_path = os.path.join(save_path, yyyy, output_name)
                print("path: ", os.path.dirname(output_path))
                os.makedirs(os.path.dirname(output_path), exist_ok=True)

                cmd = [
                    "ffmpeg", "-y",
                    "-framerate", "6",
                    "-i", os.path.join(temp_dir, "%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    output_path
                ]
                subprocess.run(cmd, check=True)
                results[date_str] = f"{save_path}{yyyy}/{output_name}"

            except Exception as e:
                print(f"[{date_str}] Movie generation failed: {e}")
                results[date_str] = None
            finally:
                # After the movie is generated, it cleans up the temporary symlinks only:
                shutil.rmtree(temp_dir)

            current_date += timedelta(days=1)

    except Exception as e:
        print(f"[ERROR] Failed to process date range: {e}")

    return results
# Example usage:
# paths = generate_movies_from_date_range('2025-04-25', '2025-04-27')
# print(paths)


##=========================
def gen_movie_from_trange(start_time_str, end_time_str, save_path='./', output_name=None):
    """
    Generate a movie from LWA synoptic image PNGs within a given time range.

    Args:
        start_time_str (str): start time in 'YYYY-MM-DD HH:MM:SS'
        end_time_str (str): end time in 'YYYY-MM-DD HH:MM:SS'
        save_path (str): directory of the output movie
        output_name (str): movie name, eg. 'tmp_movie.mp4'

    Returns:
        Path to the saved movie file, or None if failed
    """
    try:
        start_time = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")

        # Collect directories between date range
        current_date = start_time.date()
        end_date = end_time.date()
        all_png_files = []

        # Method 1
        while current_date <= end_date:
            yyyy, mm, dd = current_date.strftime("%Y"), current_date.strftime("%m"), current_date.strftime("%d")
            img_dir = f"/common/webplots/lwa-data/qlook_images/slow/synop/{yyyy}/{mm}/{dd}"
            all_png_files += sorted(glob(os.path.join(img_dir, "*.png")))
            current_date += timedelta(days=1)
        def extract_timestamp(path):
            base = os.path.basename(path)
            try:
                tstr = base.split("T")[1][:6]  # 'HHMMSS'
                dstr = base.split("T")[0].split(".")[-1]  # 'YYYY-MM-DD'
                return datetime.strptime(dstr + tstr, "%Y-%m-%d%H%M%S")
            except Exception:
                return None
        ## support >python3.8
        # png_files = [f for f in all_png_files if (ts := extract_timestamp(f)) and start_time <= ts <= end_time]
        png_files = []
        for f in all_png_files:
            ts = extract_timestamp(f)
            if ts and start_time <= ts <= end_time:
                png_files.append(f)

        # # Method 2, directly from SQL database, using:
        # file_lists, obs_times = get_lwa_file_lists_from_mysql(start_time.isoformat(), end_time.isoformat(), image_type="mfs")
        # png_files = convert_slow_hdf_to_existing_png(file_lists['slow_lev1'])

        if not png_files:
            print(f"[{start_time_str} - {end_time_str}] No PNGs in this time range.")
            return None

        print(f"[{start_time_str} - {end_time_str}] {len(png_files)} PNGs found.")
        temp_dir = tempfile.mkdtemp()
        print("Temp dir:", temp_dir)

        try:
            for i, f in enumerate(png_files):
                os.symlink(f, os.path.join(temp_dir, f"{i:06d}.png"))

            if not output_name:
                output_name = f"lwa_movie_{start_time.strftime('%Y%m%d_%H%M%S')}_{end_time.strftime('%Y%m%d_%H%M%S')}.mp4"
            output_path = os.path.join(save_path, output_name)
            os.makedirs(save_path, exist_ok=True)

            cmd = [
                "ffmpeg", "-y",
                "-framerate", "6",
                "-i", os.path.join(temp_dir, "%06d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                output_path
            ]
            subprocess.run(cmd, check=True)
            print(f"Movie saved to: {output_path}")
            return output_path

        except Exception as e:
            print(f"[{start_time_str} - {end_time_str}] Movie generation failed: {e}")
            return None
        finally:
            shutil.rmtree(temp_dir)

    except Exception as e:
        print(f"[ERROR] Failed to generate movie: {e}")
        return None
# Example usage:
# path = gen_movie_from_trange('2025-04-25 12:00:00', '2025-04-26 18:00:00')
# print(path)


##=========================
def main():
    parser = argparse.ArgumentParser(description="LWA Query and Movie Generator Utility")
    parser.add_argument('--gen', choices=['movie-daily', 'movie-trange', 'data-files-counts'], required=True,
                        help=(
                            "Generation mode: 'movie-daily' for daily movies; "
                            "'movie-trange' for a single movie over a time range; "
                            "'data-files-counts' to count files from MySQL."
                        ))
    parser.add_argument('--start', required=True,
                        help="Start date or datetime. Use 'YYYY-MM-DD' for daily, 'YYYY-MM-DD HH:MM:SS' for trange.")
    parser.add_argument('--end', required=True,
                        help="End date or datetime. Use 'YYYY-MM-DD' for daily, 'YYYY-MM-DD HH:MM:SS' for trange.")
    parser.add_argument('--out',
                        help=("Output directory" 
                            "default: /common/webplots/lwa-data/qlook_daily/movies/ for 'movie-daily' mode," 
                            "default: ./ for 'movie-trange' mode"))
    parser.add_argument('--output-name', default=None,
                        help="Optional output filename for single movie (e.g., 'movie.mp4'). Used only in 'movie-trange' mode.")
    parser.add_argument('--image-type', default='mfs', choices=['mfs', 'fch'],
                        help="Image type for querying data files (default: 'mfs')")

    args = parser.parse_args()
    if not args.out:
        if args.gen == 'movie-daily':
            args.out = '/common/webplots/lwa-data/qlook_daily/movies/'
        elif args.gen == 'movie-trange':
            args.out = './'

    if args.gen == 'movie-daily':
        print(f"Generating daily movies from {args.start} to {args.end}...")
        results = gen_daily_movies_from_date_range(args.start, args.end, save_path=args.out)
        print("\nGenerated daily movies:")
        for date_str, path in results.items():
            print(f"{date_str}: {path if path else 'No movie generated'}")

    elif args.gen == 'movie-trange':
        print(f"Generating a single movie from {args.start} to {args.end}...")
        movie_path = gen_movie_from_trange(args.start, args.end, save_path=args.out, output_name=args.output_name)
        if movie_path:
            print(f"\nMovie successfully saved to: {movie_path}")
        else:
            print("\nMovie generation failed or no data found.")

    elif args.gen == 'data-files-counts':
        print(f"Querying file list from {args.start} to {args.end} with image_type='{args.image_type}'...")
        file_lists, obs_times = get_lwa_file_lists_from_mysql(args.start, args.end, image_type=args.image_type)
        for file_type, files in file_lists.items():
            print(f"\nFor {file_type}: {len(files)} files")

if __name__ == '__main__':
    main()
