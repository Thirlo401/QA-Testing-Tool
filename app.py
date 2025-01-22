from flask import Flask, request, jsonify, render_template
import requests
from bs4 import BeautifulSoup
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'generated_scripts'

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def crawl_website(url):
    """Crawl website and extract testable elements with enhanced selector detection."""
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        elements = []
        # Find all interactive elements with expanded selector types
        selectors = [
            'input', 'button', 'a', 'form', 'select', 'textarea', 
            'label', 'div[role="button"]', 'span[role="button"]',
            'input[type="checkbox"]', 'input[type="radio"]'
        ]
        
        for element in soup.find_all(selectors):
            elem_data = {
                'tag': element.name,
                'id': element.get('id', ''),
                'class': ' '.join(element.get('class', [])),
                'type': element.get('type', ''),
                'name': element.get('name', ''),
                'placeholder': element.get('placeholder', ''),
                'value': element.get('value', ''),
                'href': element.get('href', ''),
                'role': element.get('role', ''),
                'aria-label': element.get('aria-label', ''),
                'data-testid': element.get('data-testid', ''),
                'data-cy': element.get('data-cy', ''),
                'text_content': element.get_text().strip()
            }
            elements.append(elem_data)
            
        return elements
    except Exception as e:
        print(f"Error crawling website: {e}")
        return []

def get_best_selector(element):
    """Determine the best selector strategy for an element."""
    if element['data-testid']:
        return f"[data-testid='{element['data-testid']}']"
    elif element['data-cy']:
        return f"[data-cy='{element['data-cy']}']"
    elif element['id']:
        return f"#{element['id']}"
    elif element['name']:
        return f"[name='{element['name']}']"
    elif element['aria-label']:
        return f"[aria-label='{element['aria-label']}']"
    elif element['text_content']:
        return f"contains('{element['text_content']}')"
    elif element['class']:
        return f".{element['class'].replace(' ', '.')}"
    else:
        return f"{element['tag']}"

def generate_cypress_script(url, elements):
    """Generate enhanced Cypress test script with better assertions and interactions."""
    script = f"""describe('Automated Test Suite for {url}', () => {{
  beforeEach(() => {{
    cy.visit('{url}')
    cy.wait(2000) // Wait for page load
  }})

  it('should load the page successfully', () => {{
    cy.url().should('include', '{url.split("//")[1]}')
    cy.document().should('have.property', 'readyState', 'complete')
  }})

"""
    
    for element in elements:
        selector = get_best_selector(element)
        
        if element['tag'] == 'input':
            if element['type'] == 'checkbox':
                script += f"""
  it('should interact with checkbox {selector}', () => {{
    cy.get('{selector}')
      .should('exist')
      .should('be.visible')
      .check()
      .should('be.checked')
      .uncheck()
      .should('not.be.checked')
  }})
"""
            elif element['type'] == 'radio':
                script += f"""
  it('should interact with radio button {selector}', () => {{
    cy.get('{selector}')
      .should('exist')
      .should('be.visible')
      .check()
      .should('be.checked')
  }})
"""
            else:
                script += f"""
  it('should interact with input field {selector}', () => {{
    cy.get('{selector}')
      .should('exist')
      .should('be.visible')
      .clear()
      .type('Test Input')
      .should('have.value', 'Test Input')
  }})
"""

        elif element['tag'] == 'select':
            script += f"""
  it('should interact with dropdown {selector}', () => {{
    cy.get('{selector}')
      .should('exist')
      .should('be.visible')
      .select(cy.get('{selector} option:first').invoke('val'))
      .should('have.value', cy.get('{selector} option:first').invoke('val'))
  }})
"""

        elif element['tag'] == 'button' or element['role'] == 'button':
            script += f"""
  it('should interact with button {selector}', () => {{
    cy.get('{selector}')
      .should('exist')
      .should('be.visible')
      .should('be.enabled')
  }})
"""

        elif element['tag'] == 'a':
            script += f"""
  it('should verify link {selector}', () => {{
    cy.get('{selector}')
      .should('exist')
      .should('be.visible')
      .should('have.attr', 'href')
  }})
"""

        elif element['tag'] == 'form':
            script += f"""
  it('should verify form {selector}', () => {{
    cy.get('{selector}')
      .should('exist')
      .should('be.visible')
      .within(() => {{
        cy.get('input, select, textarea').each(($el) => {{
          cy.wrap($el).should('exist')
        }})
      }})
  }})
"""

    script += """
  // Custom commands for common interactions
  Cypress.Commands.add('fillInput', (selector, value) => {
    cy.get(selector)
      .should('exist')
      .should('be.visible')
      .clear()
      .type(value)
      .should('have.value', value)
  })

  Cypress.Commands.add('selectOption', (selector, value) => {
    cy.get(selector)
      .should('exist')
      .should('be.visible')
      .select(value)
      .should('have.value', value)
  })
})"""
    return script

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/generate', methods=['POST'])
def generate_script():
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400

        elements = crawl_website(url)
        
        if not elements:
            return jsonify({'error': 'No testable elements found'}), 400

        script = generate_cypress_script(url, elements)
        
        filename = secure_filename(f"cypress_test_{url.replace('/', '_')}.js")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        with open(filepath, 'w') as f:
            f.write(script)

        return jsonify({
            'script': script,
            'filename': filename
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)