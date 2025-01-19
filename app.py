# app.py
from flask import Flask, request, jsonify, send_file, render_template
import os
from bs4 import BeautifulSoup
import requests
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'generated_scripts'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def crawl_website(url):
    """
    Crawl the website and extract elements with relevant attributes.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        elements = []
        for tag in soup.find_all():
            if tag.get("id"):
                elements.append({"tag": tag.name, "id": tag.get("id")})
            elif tag.get("name"):
                elements.append({"tag": tag.name, "name": tag.get("name")})
            elif tag.get("type"):
                elements.append({"tag": tag.name, "type": tag.get("type")})
        return elements
    except Exception as e:
        print(f"Error crawling the website: {e}")
        return []

def infer_placeholder_data(element):
    """
    Infer realistic placeholder data based on the element's attributes.
    """
    if "id" in element:
        field = element["id"].lower()
    elif "name" in element:
        field = element["name"].lower()
    else:
        field = "unknown"

    # Map field names to sample data
    if "name" in field:
        return "John"
    elif "surname" in field or "last" in field:
        return "Doe"
    elif "email" in field:
        return "johndoe@example.com"
    elif "password" in field:
        return "SecurePassword123!"
    elif "cell" in field or "phone" in field:
        return "0812345678"
    else:
        return "Sample Text"

def generate_dynamic_cypress_script(elements, target_url, output_file="cypress_script.cy.js"):
    """
    Generate a realistic Cypress script dynamically based on crawled elements.
    """
    try:
        with open(output_file, "w") as file:
            file.write("describe('Dynamic Test Suite', () => {\n\n")
            file.write("  before(() => {\n")
            file.write(f"    cy.visit('{target_url}');\n")
            file.write("  });\n\n")
            file.write("  it('fills out the form and submits it', () => {\n\n")

            for element in elements:
                if "id" in element:
                    selector = f"#{element['id']}"
                elif "name" in element:
                    selector = f'[name="{element["name"]}"]'
                else:
                    selector = element["tag"]

                placeholder = infer_placeholder_data(element)
                file.write(f"    cy.get('{selector}').type('{placeholder}');\n")

            file.write("\n  });\n")
            file.write("});\n")

    except Exception as e:
        print(f"Error generating Cypress script: {e}")

# Route for the home page
@app.route('/')
def home():
    return render_template('index.html')

# Route for generating the script
@app.route('/api/generate', methods=['POST'])
def generate_script():
    data = request.json
    target_url = data.get('url')
    
    if not target_url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        filename = f"cypress_script_{secure_filename(target_url.replace('/', '_'))}.cy.js"
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        elements = crawl_website(target_url)
        if not elements:
            return jsonify({'error': 'No elements found on the page'}), 400
            
        generate_dynamic_cypress_script(elements, target_url, output_path)
        
        return jsonify({
            'message': 'Script generated successfully',
            'filename': filename
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Route for downloading the generated script
@app.route('/api/download/<filename>')
def download_script(filename):
    try:
        return send_file(
            os.path.join(app.config['UPLOAD_FOLDER'], filename),
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 404

if __name__ == '__main__':
    app.run(debug=True)