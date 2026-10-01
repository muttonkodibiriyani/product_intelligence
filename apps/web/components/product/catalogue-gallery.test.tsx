import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';
import type { Schemas } from '@/lib/api/types';
import en from '@/messages/en.json';
import { GalleryDetails } from './catalogue-gallery';

afterEach(cleanup);

const image = (id: string): Schemas['GalleryImage'] => ({
  assetId: id,
  url: `https://media.alshaya.com/${id}.jpg`,
  sourceUrl: null,
  sha256: 'a'.repeat(64),
  width: 533,
  height: 800,
  caption: '',
  roles: [],
});

const detail: Schemas['CatalogueDetail'] = {
  retailer: 'ulta_ae',
  generation: '1',
  importedAt: '2026-10-01T10:00:00Z',
  provenance: 'archived_public_website_scrape',
  duplicateImagesRemoved: 0,
  record: {
    sku: 'parent',
    name: '<img src=x onerror=alert(1)>',
    productType: 'configurable',
    isVariant: false,
    sourceIds: { stockId: 10, catalogueId: 'opaque-source-id' },
    groupingMasterSku: 'parent',
    excludedParentSummary: true,
    capturedAt: '2026-09-30T23:00:00Z',
    children: [
      { sku: 'child', selections: [] },
      { sku: 'missing', selections: [] },
    ],
    parents: [],
    imageIds: ['a', 'b'],
  },
  parents: [],
  children: [
    {
      sku: 'child',
      resolved: true,
      name: 'Red',
      sourceIds: { stockId: 11 },
      selections: [],
      selectionLabels: ['Red'],
    },
    { sku: 'missing', resolved: false, name: null, sourceIds: null, selections: [], selectionLabels: [] },
  ],
  images: [image('a'), image('b')],
};

describe('SKU galleries', () => {
  it('switches images and variants, preserves unknown children, and escapes retailer text', () => {
    const select = vi.fn();
    const { container } = render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <GalleryDetails detail={detail} onSelect={select} />
      </NextIntlClientProvider>,
    );
    expect(container.querySelector('img[src="x"]')).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Image 2 of 2' }));
    expect(screen.getByRole('link', { name: 'Open image' }).getAttribute('href')).toBe(
      'https://media.alshaya.com/b.jpg',
    );
    fireEvent.click(screen.getByRole('button', { name: /Red.*child/ }));
    expect(select).toHaveBeenCalledWith('child');
    const missing = screen.getByRole('button', { name: /missing.*Not captured/ });
    expect(missing.hasAttribute('disabled')).toBe(true);
    fireEvent.click(missing);
    expect(select).toHaveBeenCalledTimes(1);
  });

  it('shows the image gap instead of an invented placeholder image', () => {
    const { container } = render(
      <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
        <GalleryDetails detail={{ ...detail, images: [] }} onSelect={vi.fn()} />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText('No captured image available')).toBeTruthy();
    expect(container.querySelector('img')).toBeNull();
  });
});
