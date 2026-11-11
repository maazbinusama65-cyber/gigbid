import { paginate } from './paginate';

test('loadBrowser returns null cursor on last page', () => {
  expect(paginate([1, 2, 3], 0, 5).next).toBeNull();
});
