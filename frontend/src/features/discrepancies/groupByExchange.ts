export interface ExchangeGroupOf<T> {
  exchange: string;
  items: T[];
}

/**
 * The items of one list under their exchange, whatever tab was last selected (owner decision 66, Q6). The groups
 * come in the order the route first names each exchange, and the items keep the route's order inside a group:
 * the route sorts the bookings newest first, so the exchange of the newest booking comes first.
 */
export function groupByExchange<T extends { exchange: string }>(items: readonly T[]): ExchangeGroupOf<T>[] {
  const groups: ExchangeGroupOf<T>[] = [];
  for (const item of items) {
    const known = groups.find((group) => group.exchange === item.exchange);
    if (known === undefined) groups.push({ exchange: item.exchange, items: [item] });
    else known.items.push(item);
  }
  return groups;
}
