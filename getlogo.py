import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
import os
import uuid
import zipfile
from urllib.parse import urljoin, urlparse
from PIL import Image
from io import BytesIO
import time
import csv

def get_site_logo(url):
    """
    Scrape a website to find and download its logo image.
    Returns the logo info or None if no logo was found.
    """
    # Make sure URL has proper format
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    try:
        # Send a request to get the website content
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors
        
        # Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for common logo patterns
        logo_candidates = []
        
        # 1. Check for link tags with 'icon' or 'logo' in the rel attribute
        for link in soup.find_all('link'):
            rel = link.get('rel', [])
            if isinstance(rel, list):
                rel = ' '.join(rel).lower()
            else:
                rel = str(rel).lower()
                
            if ('icon' in rel or 'logo' in rel) and link.get('href'):
                logo_candidates.append((link.get('href'), 1))  # Lower priority
        
        # 2. Look for images with 'logo' in the class, id, or alt attribute
        for img in soup.find_all('img'):
            score = 0
            for attr in ['class', 'id', 'alt', 'src']:
                value = img.get(attr, '')
                if isinstance(value, list):
                    value = ' '.join(value)
                else:
                    value = str(value)
                    
                if 'logo' in value.lower():
                    score += 2
                
            if score > 0 and img.get('src'):
                logo_candidates.append((img.get('src'), score + 2))  # Higher priority
        
        # If no logo candidates found, look for the first image in the header
        if not logo_candidates:
            header = soup.find('header')
            if header:
                img = header.find('img')
                if img and img.get('src'):
                    logo_candidates.append((img.get('src'), 3))  # Medium priority
        
        # Sort by priority (highest first)
        logo_candidates.sort(key=lambda x: x[1], reverse=True)
        
        # Process logo candidates
        for img_url, _ in logo_candidates:
            # Convert relative URLs to absolute URLs
            img_url = urljoin(url, img_url)
            
            try:
                # Download the image
                img_response = requests.get(img_url, headers=headers, timeout=10)
                img_response.raise_for_status()
                
                # Check if it's a valid image
                img = Image.open(BytesIO(img_response.content))
                
                # Determine best format - keep original format if possible
                save_format = img.format if img.format in ('JPEG', 'PNG') else 'PNG'
                ext = 'jpg' if save_format == 'JPEG' else 'png'
                
                # Convert to RGB if needed (for RGBA images)
                if img.mode == 'RGBA' and save_format == 'JPEG':
                    # Create a white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    # Paste using alpha channel as mask
                    background.paste(img, mask=img.split()[3])
                    img = background
                elif img.mode != 'RGB' and save_format == 'JPEG':
                    img = img.convert('RGB')
                
                # Generate a unique filename
                domain = urlparse(url).netloc
                filename = f"{domain.replace('.', '_')}_{uuid.uuid4().hex[:8]}.{ext}"
                
                # Create images directory if it doesn't exist
                os.makedirs('logos', exist_ok=True)
                
                # Save the image
                img_path = os.path.join('logos', filename)
                img.save(img_path, save_format)
                
                # Return all the image information
                return {
                    'path': img_path,
                    'filename': filename,
                    'format': ext,
                    'domain': domain,
                    'url': url
                }
            
            except Exception as e:
                continue  # Try the next candidate if this one fails
        
        return None  # No valid logo found
        
    except Exception as e:
        st.error(f"Error processing {url}: {str(e)}")
        return None

def create_mapping_file(mapping_data):
    """
    Create a CSV file mapping website URLs to logo filenames.
    """
    filename = "logo_mapping.csv"
    with open(filename, 'w', newline='') as csvfile:
        fieldnames = ['website_url', 'domain', 'logo_filename', 'google_drive_url']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        
        writer.writeheader()
        for data in mapping_data:
            writer.writerow({
                'website_url': data['url'],
                'domain': data['domain'],
                'logo_filename': data['filename'],
                'google_drive_url': ''  # Empty column to be filled after Google Drive upload
            })
    
    return filename

def main():
    st.title("Website Logo Scraper with Mapping File")
    st.write("Upload an Excel file with website URLs to extract logos and create a mapping file for Google Drive")
    
    # Use session state to store file data for downloads
    if 'has_run' not in st.session_state:
        st.session_state.has_run = False
        st.session_state.zip_data = None
        st.session_state.mapping_data = None
        st.session_state.excel_data = None
        st.session_state.all_logos = []
    
    uploaded_file = st.file_uploader("Choose an Excel file", type=["xlsx", "xls", "csv"])
    
    if uploaded_file:
        try:
            # Read the uploaded file
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            
            # Check if the DataFrame has any columns
            if df.empty or len(df.columns) == 0:
                st.error("The uploaded file is empty or has no columns.")
                return
            
            # Let the user select the column containing URLs
            url_column = st.selectbox("Select the column containing website URLs", df.columns)
            
            if st.button("Extract Logos") or st.session_state.has_run:
                # Skip processing if already run
                if not st.session_state.has_run:
                    # Add a progress bar
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    # Store the image data and mapping info
                    all_logos = []
                    mapping_data = []
                    
                    # Create new columns for results
                    df['logo_found'] = False
                    df['logo_filename'] = None
                    
                    # Process each URL
                    for i, row in df.iterrows():
                        url = str(row[url_column])
                        status_text.text(f"Processing {i+1}/{len(df)}: {url}")
                        
                        # Get the logo
                        logo_info = get_site_logo(url)
                        
                        # Update the DataFrame and mapping data
                        if logo_info:
                            df.at[i, 'logo_found'] = True
                            df.at[i, 'logo_filename'] = logo_info['filename']
                            all_logos.append(logo_info)
                            mapping_data.append({
                                'url': url,
                                'domain': logo_info['domain'],
                                'filename': logo_info['filename']
                            })
                        
                        # Update progress
                        progress_bar.progress((i + 1) / len(df))
                        
                        # Small delay to prevent overwhelming websites
                        time.sleep(0.5)
                    
                    # Create a zip file with all logos
                    if all_logos:
                        zip_filename = "all_logos.zip"
                        with zipfile.ZipFile(zip_filename, 'w') as zipf:
                            for logo in all_logos:
                                zipf.write(logo['path'], logo['filename'])
                        
                        # Store zip data in session state
                        with open(zip_filename, "rb") as f:
                            st.session_state.zip_data = f.read()
                    
                    # Create mapping file
                    if mapping_data:
                        mapping_filename = create_mapping_file(mapping_data)
                        
                        # Store mapping data in session state
                        with open(mapping_filename, "rb") as f:
                            st.session_state.mapping_data = f.read()
                    
                    # Save the results to Excel
                    output_filename = "logos_extraction_results.xlsx"
                    df.to_excel(output_filename, index=False)
                    
                    # Store Excel data in session state
                    with open(output_filename, "rb") as file:
                        st.session_state.excel_data = file.read()
                    
                    # Store logos in session state
                    st.session_state.all_logos = all_logos
                    
                    # Set the flag to indicate processing is done
                    st.session_state.has_run = True
                
                # Display the results (whether just processed or retrieved from session state)
                success_count = sum(1 for logo in st.session_state.all_logos)
                st.success(f"Processed {len(df)} websites. Successfully extracted {success_count} logos.")
                
                # Display download buttons (these will persist because they use session state data)
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    if st.session_state.zip_data:
                        st.download_button(
                            label="Download All Logos (ZIP)",
                            data=st.session_state.zip_data,
                            file_name="all_logos.zip",
                            mime="application/zip",
                            key="zip_download"
                        )
                
                with col2:
                    if st.session_state.mapping_data:
                        st.download_button(
                            label="Download Mapping File (CSV)",
                            data=st.session_state.mapping_data,
                            file_name="logo_mapping.csv",
                            mime="text/csv",
                            key="mapping_download"
                        )
                
                with col3:
                    if st.session_state.excel_data:
                        st.download_button(
                            label="Download Results (Excel)",
                            data=st.session_state.excel_data,
                            file_name="logos_extraction_results.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="excel_download"
                        )
                
                # Show how to use the mapping file
                st.subheader("Next Steps for Google Drive Integration")
                st.markdown("""
                1. **Extract the logo files** from the ZIP download
                2. **Upload the logos to Google Drive** in a shared folder
                3. **For each logo in Google Drive**:
                   - Get the sharing link (right-click > "Get link")
                   - Convert to direct link format: `https://drive.google.com/uc?export=view&id=FILE_ID`
                   - Update the `google_drive_url` column in the mapping CSV
                4. **Use the updated mapping file** for your Webflow CMS import
                """)
                
                # Show thumbnails of the extracted logos
                if st.session_state.all_logos:
                    st.subheader("Extracted Logos")
                    
                    # Create a grid layout
                    cols = st.columns(3)
                    for i, logo in enumerate(st.session_state.all_logos):
                        col = cols[i % 3]
                        with col:
                            st.image(logo['path'], caption=f"{logo['domain']}", width=150)
                
                # Button to reset and run again
                if st.button("Reset and Run Again"):
                    st.session_state.has_run = False
                    st.session_state.zip_data = None
                    st.session_state.mapping_data = None
                    st.session_state.excel_data = None
                    st.session_state.all_logos = []
                    st.experimental_rerun()
        
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            st.exception(e)

if __name__ == "__main__":
    main()
