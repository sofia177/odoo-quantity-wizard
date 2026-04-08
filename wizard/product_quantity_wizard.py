from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ProductQuantityWizard(models.TransientModel):#temporary wizard data
    _name = 'product.quantity.wizard'
    _description = 'Product Quantity Wizard'

    # ── Step 1: Operation 
    operation = fields.Selection(
        selection=[
            ('update', 'Update  –  add or remove from existing quantity'),
            ('set',    'Set  –  define an exact quantity'),
        ],
        string='Operation',
        required=True,
    )

    # ── Step 2: Location 
    location_set = fields.Boolean(
        string='Specify a location?',
        default=False,
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        domain=[('usage', '=', 'internal')],
    )

    # ── Step 3: Quantity 
    quantity = fields.Float(
        string='Quantity',
        digits='Product Unit of Measure',
    )

    # ── Product (passed from the product form) 
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        related='product_id.uom_id',
        string='Unit of Measure',
        readonly=True,
    )

    # ── Computed helper fields (show what will happen based on choices)(smart ui)
    action_description = fields.Char(
        string='What will happen',
        compute='_compute_action_description',
    )
    show_location = fields.Boolean(
        compute='_compute_show_location',
    )
    show_quantity = fields.Boolean(
        compute='_compute_show_quantity',
    )


    # Computes


    @api.depends('operation', 'location_set', 'quantity')
    def _compute_action_description(self):
        for wiz in self:
            op  = wiz.operation
            loc = wiz.location_set
            qty = wiz.quantity

            if not op:
                wiz.action_description = ''
                continue

            if op == 'set':
                if loc:
                    wiz.action_description = _(
                        ' Set quantity — sets an exact quantity at the chosen location.'
                    )
                else:
                    wiz.action_description = _(
                        ' Make all locations — applies the quantity to every internal location.'
                    )

            elif op == 'update':
                if loc and qty is not None:
                    if qty >= 0:
                        wiz.action_description = _(
                            '✔  Normal update — adds %(qty)s to the chosen location.',
                            qty=qty,
                        )
                    else:
                        wiz.action_description = _(
                            '!  Check availability — stock will be verified before deducting %(qty)s.',
                            qty=abs(qty),
                        )
                elif not loc and qty is not None:
                    if qty >= 0:
                        wiz.action_description = _(
                            '↗  Any location — positive update spread across available locations.'
                        )
                    else:
                        wiz.action_description = _(
                            '≡  Available quantity — negative update drawn from total available stock.'
                        )
                else:
                    wiz.action_description = ''

    @api.depends('operation')
    def _compute_show_location(self):
        for wiz in self:
            wiz.show_location = bool(wiz.operation)

    @api.depends('operation')
    def _compute_show_quantity(self):
        for wiz in self:
            wiz.show_quantity = bool(wiz.operation)

    # Constraints

    @api.constrains('location_set', 'location_id')
    def _check_location(self):
        for wiz in self:
            if wiz.location_set and not wiz.location_id:
                raise ValidationError(_('Please choose a location or uncheck "Specify a location?".'))

    @api.constrains('operation', 'location_set', 'quantity')
    def _check_availability(self):
        """For UPDATE + location set + negative qty: verify available stock."""
        for wiz in self:
            if (
                wiz.operation == 'update'
                and wiz.location_set
                and wiz.location_id
                and wiz.quantity < 0
            ):
                quant = self.env['stock.quant'].search([
                    ('product_id', '=', wiz.product_id.id),
                    ('location_id', '=', wiz.location_id.id),
                ], limit=1)
                available = quant.quantity if quant else 0.0
                if available + wiz.quantity < 0:
                    raise ValidationError(_(
                        'Not enough stock at %(loc)s.\n'
                        'Available: %(avail)s  |  Requested deduction: %(req)s',
                        loc=wiz.location_id.display_name,
                        avail=available,
                        req=abs(wiz.quantity),
                    ))

    
    # Action


    def action_apply(self):
        self.ensure_one()
        op  = self.operation
        loc = self.location_set
        qty = self.quantity

        if op == 'set':
            self._do_set(loc)
        elif op == 'update':
            self._do_update(loc, qty)

        return {'type': 'ir.actions.act_window_close'}

    # ── Private helpers 

    def _do_set(self, location_set):
        """
        SET operation:
          • location set   → set exact quantity at that location
          • location not set → set quantity on ALL internal locations
        """
        Quant = self.env['stock.quant']

        if location_set:
            # set quantity — single location
            Quant._update_available_quantity(
                self.product_id,
                self.location_id,
                self.quantity,
            )
            # Use Odoo's inventory adjustment helper when available (v16+)
            quant = Quant.search([
                ('product_id', '=', self.product_id.id),
                ('location_id', '=', self.location_id.id),
            ], limit=1)
            if quant:
                quant.with_context(inventory_mode=True).inventory_quantity = self.quantity
                quant.action_apply_inventory()
            else:
                Quant.with_context(inventory_mode=True).create({
                    'product_id': self.product_id.id,
                    'location_id': self.location_id.id,
                    'inventory_quantity': self.quantity,
                }).action_apply_inventory()
        else:
            # make all locations — apply to every internal location
            locations = self.env['stock.location'].search([('usage', '=', 'internal')])
            for loc in locations:
                quant = Quant.search([
                    ('product_id', '=', self.product_id.id),
                    ('location_id', '=', loc.id),
                ], limit=1)
                if quant:
                    quant.with_context(inventory_mode=True).inventory_quantity = self.quantity
                    quant.action_apply_inventory()
                else:
                    Quant.with_context(inventory_mode=True).create({
                        'product_id': self.product_id.id,
                        'location_id': loc.id,
                        'inventory_quantity': self.quantity,
                    }).action_apply_inventory()

    def _do_update(self, location_set, qty):
      
        Quant = self.env['stock.quant']

        if location_set:
            if qty >= 0:
                # ── Normal update ──────────────────────────────────────────
                Quant._update_available_quantity(
                    self.product_id, self.location_id, qty
                )
            else:
                # ── Check availability (already validated in constrains) ───
                Quant._update_available_quantity(
                    self.product_id, self.location_id, qty
                )
        else:
            if qty >= 0:
                # ── Any location: prefer first location with existing stock ─
                quant = Quant.search([
                    ('product_id', '=', self.product_id.id),
                    ('location_id.usage', '=', 'internal'),
                    ('quantity', '>', 0),
                ], order='quantity desc', limit=1)
                target_location = (
                    quant.location_id if quant
                    else self.env.ref('stock.stock_location_stock', raise_if_not_found=False)
                    or self.env['stock.location'].search([('usage', '=', 'internal')], limit=1)
                )
                Quant._update_available_quantity(self.product_id, target_location, qty)

            else:
                # ── Available quantity: deduct from locations with stock ────
                remaining = abs(qty)
                quants = Quant.search([
                    ('product_id', '=', self.product_id.id),
                    ('location_id.usage', '=', 'internal'),
                    ('quantity', '>', 0),
                ], order='quantity desc')

                total_available = sum(quants.mapped('quantity'))
                if total_available < remaining:
                    raise UserError(_(
                        'Not enough stock across all locations.\n'
                        'Total available: %(avail)s  |  Requested: %(req)s',
                        avail=total_available,
                        req=remaining,
                    ))

                for quant in quants:
                    if remaining <= 0:
                        break
                    deduct = min(quant.quantity, remaining)
                    Quant._update_available_quantity(
                        self.product_id, quant.location_id, -deduct
                    )
                    remaining -= deduct 