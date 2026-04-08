{
    'name': 'Product Quantity Wizard',
    'version': '18.0.1.0.0',
    'summary': 'Wizard to update or set product quantities from the product form',
    'category': 'Inventory',
    'author': 'ChocoArt',
    'depends': ['product', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_quantity_wizard_view.xml',
        'views/product_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
