from flask import Flask, request, render_template, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///restaurant.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# ---------------- Models ----------------

class MenuItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # starter, main, dessert, drink
    price = db.Column(db.Float, nullable=False)
    available = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "price": self.price,
            "available": self.available
        }


class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    quantity = db.Column(db.Float, nullable=False, default=0)
    unit = db.Column(db.String(20), nullable=False, default='units')
    low_stock_threshold = db.Column(db.Float, nullable=False, default=5)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "quantity": self.quantity,
            "unit": self.unit,
            "low_stock_threshold": self.low_stock_threshold,
            "low_stock": self.quantity <= self.low_stock_threshold
        }


class Table(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, nullable=False, unique=True)
    capacity = db.Column(db.Integer, nullable=False, default=2)
    status = db.Column(db.String(20), default='available')  # available, occupied, reserved

    def to_dict(self):
        return {
            "id": self.id,
            "number": self.number,
            "capacity": self.capacity,
            "status": self.status
        }


class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('table.id'), nullable=False)
    customer_name = db.Column(db.String(120), nullable=False)
    party_size = db.Column(db.Integer, nullable=False)
    reservation_time = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='active')  # active, cancelled

    table = db.relationship('Table', backref='reservations')

    def to_dict(self):
        return {
            "id": self.id,
            "table_id": self.table_id,
            "table_number": self.table.number if self.table else None,
            "customer_name": self.customer_name,
            "party_size": self.party_size,
            "reservation_time": self.reservation_time,
            "status": self.status
        }


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    table_id = db.Column(db.Integer, db.ForeignKey('table.id'), nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, preparing, served, paid, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    table = db.relationship('Table', backref='orders')
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade="all, delete-orphan")

    def total(self):
        return sum(i.quantity * i.menu_item.price for i in self.items if i.menu_item)

    def to_dict(self):
        return {
            "id": self.id,
            "table_id": self.table_id,
            "table_number": self.table.number if self.table else None,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "items": [i.to_dict() for i in self.items],
            "total": round(self.total(), 2)
        }


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_item.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    menu_item = db.relationship('MenuItem')

    def to_dict(self):
        return {
            "id": self.id,
            "menu_item_id": self.menu_item_id,
            "name": self.menu_item.name if self.menu_item else None,
            "price": self.menu_item.price if self.menu_item else None,
            "quantity": self.quantity,
            "subtotal": round(self.quantity * self.menu_item.price, 2) if self.menu_item else 0
        }


# ---------------- Page route ----------------

@app.route('/')
def index():
    return render_template('index.html')


# ---------------- Menu APIs ----------------

@app.route('/api/menu', methods=['GET'])
def list_menu():
    items = MenuItem.query.order_by(MenuItem.category, MenuItem.name).all()
    return jsonify([i.to_dict() for i in items])


@app.route('/api/menu', methods=['POST'])
def add_menu_item():
    data = request.get_json() if request.is_json else request.form
    name = data.get('name', '').strip()
    category = data.get('category', '').strip()
    price = data.get('price')

    if not name or not category or price is None:
        return jsonify({"error": "name, category and price are required"}), 400

    try:
        price = float(price)
    except ValueError:
        return jsonify({"error": "price must be a number"}), 400

    item = MenuItem(name=name, category=category, price=price, available=True)
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@app.route('/api/menu/<int:item_id>/toggle', methods=['POST'])
def toggle_menu_item(item_id):
    item = MenuItem.query.get(item_id)
    if not item:
        return jsonify({"error": "Menu item not found"}), 404
    item.available = not item.available
    db.session.commit()
    return jsonify(item.to_dict())


@app.route('/api/menu/<int:item_id>', methods=['DELETE'])
def delete_menu_item(item_id):
    item = MenuItem.query.get(item_id)
    if not item:
        return jsonify({"error": "Menu item not found"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "Menu item deleted"}), 200


# ---------------- Table APIs ----------------

@app.route('/api/tables', methods=['GET'])
def list_tables():
    tables = Table.query.order_by(Table.number).all()
    return jsonify([t.to_dict() for t in tables])


@app.route('/api/tables', methods=['POST'])
def add_table():
    data = request.get_json() if request.is_json else request.form
    number = data.get('number')
    capacity = data.get('capacity', 2)

    if number is None:
        return jsonify({"error": "table number is required"}), 400

    try:
        number = int(number)
        capacity = int(capacity)
    except ValueError:
        return jsonify({"error": "number and capacity must be integers"}), 400

    if Table.query.filter_by(number=number).first():
        return jsonify({"error": "Table number already exists"}), 400

    table = Table(number=number, capacity=capacity, status='available')
    db.session.add(table)
    db.session.commit()
    return jsonify(table.to_dict()), 201


# ---------------- Reservation APIs ----------------

@app.route('/api/reservations', methods=['GET'])
def list_reservations():
    reservations = Reservation.query.order_by(Reservation.id.desc()).all()
    return jsonify([r.to_dict() for r in reservations])


@app.route('/api/reservations', methods=['POST'])
def create_reservation():
    data = request.get_json() if request.is_json else request.form
    table_id = data.get('table_id')
    customer_name = data.get('customer_name', '').strip()
    party_size = data.get('party_size')
    reservation_time = data.get('reservation_time', '').strip()

    if not table_id or not customer_name or not party_size or not reservation_time:
        return jsonify({"error": "table_id, customer_name, party_size and reservation_time are required"}), 400

    table = Table.query.get(table_id)
    if not table:
        return jsonify({"error": "Table not found"}), 404

    if table.status != 'available':
        return jsonify({"error": f"Table {table.number} is not available"}), 400

    try:
        party_size = int(party_size)
    except ValueError:
        return jsonify({"error": "party_size must be an integer"}), 400

    if party_size > table.capacity:
        return jsonify({"error": f"Table {table.number} capacity is {table.capacity}, party size too large"}), 400

    reservation = Reservation(
        table_id=table_id,
        customer_name=customer_name,
        party_size=party_size,
        reservation_time=reservation_time,
        status='active'
    )
    table.status = 'reserved'
    db.session.add(reservation)
    db.session.commit()
    return jsonify(reservation.to_dict()), 201


@app.route('/api/reservations/<int:reservation_id>/cancel', methods=['POST'])
def cancel_reservation(reservation_id):
    reservation = Reservation.query.get(reservation_id)
    if not reservation:
        return jsonify({"error": "Reservation not found"}), 404

    reservation.status = 'cancelled'
    if reservation.table and reservation.table.status == 'reserved':
        reservation.table.status = 'available'

    db.session.commit()
    return jsonify(reservation.to_dict())


# ---------------- Order APIs ----------------

@app.route('/api/orders', methods=['GET'])
def list_orders():
    status = request.args.get('status')
    query = Order.query
    if status:
        query = query.filter_by(status=status)
    orders = query.order_by(Order.created_at.desc()).all()
    return jsonify([o.to_dict() for o in orders])


@app.route('/api/orders', methods=['POST'])
def create_order():
    data = request.get_json() if request.is_json else request.form
    table_id = data.get('table_id')
    items = data.get('items', [])  # [{menu_item_id, quantity}]

    if not items:
        return jsonify({"error": "order must include at least one item"}), 400

    if table_id:
        table = Table.query.get(table_id)
        if not table:
            return jsonify({"error": "Table not found"}), 404
        table.status = 'occupied'

    order = Order(table_id=table_id, status='pending')
    db.session.add(order)
    db.session.flush()

    for entry in items:
        menu_item_id = entry.get('menu_item_id')
        quantity = entry.get('quantity', 1)

        menu_item = MenuItem.query.get(menu_item_id)
        if not menu_item:
            db.session.rollback()
            return jsonify({"error": f"Menu item {menu_item_id} not found"}), 404
        if not menu_item.available:
            db.session.rollback()
            return jsonify({"error": f"'{menu_item.name}' is currently unavailable"}), 400

        try:
            quantity = int(quantity)
        except ValueError:
            quantity = 1

        order_item = OrderItem(order_id=order.id, menu_item_id=menu_item_id, quantity=quantity)
        db.session.add(order_item)

    db.session.commit()
    return jsonify(order.to_dict()), 201


@app.route('/api/orders/<int:order_id>/status', methods=['POST'])
def update_order_status(order_id):
    order = Order.query.get(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    data = request.get_json() if request.is_json else request.form
    new_status = data.get('status', '').strip()

    valid_statuses = ['pending', 'preparing', 'served', 'paid', 'cancelled']
    if new_status not in valid_statuses:
        return jsonify({"error": f"status must be one of {valid_statuses}"}), 400

    order.status = new_status

    # Free up the table when order is paid or cancelled
    if new_status in ('paid', 'cancelled') and order.table:
        order.table.status = 'available'

    db.session.commit()
    return jsonify(order.to_dict())


# ---------------- Inventory APIs ----------------

@app.route('/api/inventory', methods=['GET'])
def list_inventory():
    items = InventoryItem.query.order_by(InventoryItem.name).all()
    return jsonify([i.to_dict() for i in items])


@app.route('/api/inventory', methods=['POST'])
def add_inventory_item():
    data = request.get_json() if request.is_json else request.form
    name = data.get('name', '').strip()
    quantity = data.get('quantity', 0)
    unit = data.get('unit', 'units').strip()
    threshold = data.get('low_stock_threshold', 5)

    if not name:
        return jsonify({"error": "name is required"}), 400

    if InventoryItem.query.filter_by(name=name).first():
        return jsonify({"error": "Inventory item already exists"}), 400

    try:
        quantity = float(quantity)
        threshold = float(threshold)
    except ValueError:
        return jsonify({"error": "quantity and threshold must be numbers"}), 400

    item = InventoryItem(name=name, quantity=quantity, unit=unit, low_stock_threshold=threshold)
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@app.route('/api/inventory/<int:item_id>/update', methods=['POST'])
def update_inventory(item_id):
    item = InventoryItem.query.get(item_id)
    if not item:
        return jsonify({"error": "Inventory item not found"}), 404

    data = request.get_json() if request.is_json else request.form
    delta = data.get('delta')  # positive to add stock, negative to remove

    if delta is None:
        return jsonify({"error": "delta is required"}), 400

    try:
        delta = float(delta)
    except ValueError:
        return jsonify({"error": "delta must be a number"}), 400

    item.quantity = max(0, item.quantity + delta)
    db.session.commit()
    return jsonify(item.to_dict())


# ---------------- Reports ----------------

@app.route('/api/reports/sales', methods=['GET'])
def sales_report():
    paid_orders = Order.query.filter_by(status='paid').all()
    total_sales = sum(o.total() for o in paid_orders)
    return jsonify({
        "total_orders": len(paid_orders),
        "total_sales": round(total_sales, 2)
    })


@app.route('/api/reports/low-stock', methods=['GET'])
def low_stock_report():
    items = InventoryItem.query.all()
    low = [i.to_dict() for i in items if i.quantity <= i.low_stock_threshold]
    return jsonify(low)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)